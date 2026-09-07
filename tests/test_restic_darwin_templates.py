#!/usr/bin/env python3
"""Regression tests for the restic-darwin templates."""

import os
import pathlib
import shlex
import subprocess
import tempfile
import textwrap
import unittest


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
ROLE = REPO_ROOT / "roles" / "restic-darwin"
FILES = ROLE / "files"
TASKS = ROLE / "tasks" / "main.yml"
TEMPLATES = ROLE / "templates"


class ResticDarwinTemplateTest(unittest.TestCase):
    def render_backup(self, home: pathlib.Path, bin_dir: pathlib.Path) -> str:
        template = (TEMPLATES / "restic-s3-backup.j2").read_text()
        replacements = {
            "{{ home }}": str(home),
            "{{ restic_darwin.keep_daily }}": "30",
            "{{ restic_darwin.keep_monthly }}": "12",
            "{{ restic_darwin.keep_weekly }}": "8",
            "{{ restic_darwin.materialise_timeout_seconds }}": "1",
            "{{ restic_darwin.min_interval_hours }}": "20",
            "{{ restic_darwin.repo_name }}": "test-host",
            "{{ restic_darwin.s3_bucket }}": "example-bucket",
            "{{ restic_darwin.s3_region }}": "ap-northeast-1",
            'export PATH="/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"': (
                f'export PATH="{bin_dir}:/usr/bin:/bin:/usr/sbin:/sbin"'
            ),
        }
        for source, destination in replacements.items():
            template = template.replace(source, destination)
        self.assertNotIn("{{", template)
        return template

    def run_backup(
        self,
        backup_rc: int,
        setup=None,
        materialise_poll_seconds: int = 5,
    ) -> tuple[subprocess.CompletedProcess[str], pathlib.Path, str, str]:
        temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(temporary_directory.cleanup)
        root = pathlib.Path(temporary_directory.name)
        home = root / "home"
        bin_dir = root / "bin"
        calls = root / "calls"
        notifications = root / "notifications"
        (home / ".config" / "restic").mkdir(parents=True)
        (home / ".config" / "restic" / "s3.env").write_text("")
        (home / ".local" / "bin").mkdir(parents=True)
        (home / "Library" / "Logs").mkdir(parents=True)
        (home / "Library" / "Mobile Documents").mkdir(parents=True)
        bin_dir.mkdir()

        self.write_executable(
            bin_dir / "pmset",
            "#!/bin/sh\necho 'Now drawing from AC Power'\n",
        )
        self.write_executable(
            bin_dir / "osascript",
            f"#!/bin/sh\nprintf '%s\\n' \"$*\" >> {notifications!s}\n",
        )
        self.write_executable(
            bin_dir / "restic",
            textwrap.dedent(
                f"""\
                #!/bin/sh
                printf '%s\\n' "$1" >> {calls!s}
                if [ "$1" = backup ]; then
                    exit "${{RESTIC_BACKUP_RC}}"
                fi
                exit 0
                """
            ),
        )

        if setup is not None:
            setup(home, bin_dir)

        script = root / "restic-s3-backup"
        rendered = self.render_backup(home, bin_dir)
        rendered = rendered.replace("    sleep 5", f"    sleep {materialise_poll_seconds}")
        script.write_text(rendered)
        script.chmod(0o755)
        environment = os.environ.copy()
        environment["RESTIC_BACKUP_RC"] = str(backup_rc)
        result = subprocess.run(
            [str(script)],
            capture_output=True,
            check=False,
            env=environment,
            text=True,
        )
        call_log = calls.read_text() if calls.exists() else ""
        notification_log = notifications.read_text() if notifications.exists() else ""
        return result, home, call_log, notification_log

    @staticmethod
    def write_executable(path: pathlib.Path, content: str) -> None:
        path.write_text(content)
        path.chmod(0o755)

    def test_backup_exit_code_zero_marks_success_and_runs_retention(self) -> None:
        result, home, calls, notifications = self.run_backup(0)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((home / ".local/state/restic-s3-backup.success").exists())
        self.assertTrue((home / ".local/state/restic-s3-backup.retention").exists())
        self.assertEqual(calls.splitlines(), ["backup", "forget"])
        self.assertEqual(notifications, "")

    def test_backup_exit_code_three_warns_marks_success_and_runs_retention(self) -> None:
        result, home, calls, notifications = self.run_backup(3)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Backup completed with unreadable source files", result.stdout)
        self.assertTrue((home / ".local/state/restic-s3-backup.success").exists())
        self.assertTrue((home / ".local/state/restic-s3-backup.retention").exists())
        self.assertEqual(calls.splitlines(), ["backup", "forget"])
        self.assertIn("Backup completed with unreadable files", notifications)

    def test_other_backup_exit_code_fails_without_markers_or_retention(self) -> None:
        result, home, calls, notifications = self.run_backup(7)

        self.assertEqual(result.returncode, 7, result.stdout + result.stderr)
        self.assertIn("restic backup failed with exit code 7", result.stdout)
        self.assertFalse((home / ".local/state/restic-s3-backup.success").exists())
        self.assertFalse((home / ".local/state/restic-s3-backup.retention").exists())
        self.assertEqual(calls.splitlines(), ["backup"])
        self.assertIn("Backup failed", notifications)

    def test_icloud_materialisation_uses_download_helper_and_waits(self) -> None:
        template = (TEMPLATES / "restic-s3-backup.j2").read_text()

        self.assertIn('ICLOUD_DOWNLOAD="{{ home }}/.local/bin/restic-icloud-download"', template)
        self.assertIn("-type d -flags +dataless", template)
        self.assertIn('-exec "${ICLOUD_DOWNLOAD}" {} \\;', template)
        self.assertIn("-type f -flags +dataless", template)
        self.assertIn('-exec "${ICLOUD_DOWNLOAD}" {} +', template)
        self.assertIn("MATERIALISE_TIMEOUT", template)
        self.assertIn("-exec printf . \\; | wc -c", template)
        self.assertIn("sleep", template)
        self.assertNotIn('cat "${path}"', template)
        self.assertNotIn("-flags +dataless 2>/dev/null", template)

    def test_materialisation_repeats_for_newly_visible_descendants(self) -> None:
        def setup(home: pathlib.Path, bin_dir: pathlib.Path) -> None:
            state = home / "materialisation-state"
            downloads = home / "download-requests"
            helper = home / ".local" / "bin" / "restic-icloud-download"
            parent = home / "Library" / "Mobile Documents" / "Parent Folder"
            child = parent / "child\nfile.txt"
            state.write_text("parent\n")
            self.write_executable(
                helper,
                textwrap.dedent(
                    f"""\
                    #!/bin/sh
                    for path do
                        printf '%s\\000' "$path" >> {shlex.quote(str(downloads))}
                    done
                    """
                ),
            )
            self.write_executable(
                bin_dir / "find",
                textwrap.dedent(
                    f"""\
                    #!/bin/sh
                    state_file={shlex.quote(str(state))}
                    helper={shlex.quote(str(helper))}
                    parent={shlex.quote(str(parent))}
                    child={shlex.quote(str(child))}
                    current=$(cat "$state_file")
                    case " $* " in
                        *" -type d "*)
                            if [ "$current" = parent ]; then
                                "$helper" "$parent"
                                echo requested_parent > "$state_file"
                            fi
                            ;;
                        *" -type f "*)
                            if [ "$current" = child ]; then
                                "$helper" "$child"
                                echo requested_child > "$state_file"
                            fi
                            ;;
                        *)
                            case "$current" in
                                requested_parent)
                                    printf .
                                    echo child > "$state_file"
                                    ;;
                                requested_child)
                                    echo done > "$state_file"
                                    ;;
                                parent|child)
                                    echo placeholder
                                    ;;
                            esac
                            ;;
                    esac
                    """
                ),
            )

        result, home, _, _ = self.run_backup(
            0,
            setup=setup,
            materialise_poll_seconds=0,
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        requests = (home / "download-requests").read_bytes().split(b"\0")
        decoded_requests = [request.decode() for request in requests if request]
        self.assertEqual(len(decoded_requests), 2)
        self.assertTrue(decoded_requests[0].endswith("Parent Folder"))
        self.assertTrue(decoded_requests[1].endswith("child\nfile.txt"))
        self.assertNotIn("/.Trash/", "\n".join(decoded_requests))
        self.assertIn("Still evicted: 1", result.stdout)
        self.assertIn("Still evicted: 0", result.stdout)

    def test_download_helper_uses_official_ubiquitous_item_api(self) -> None:
        source = (FILES / "restic-icloud-download.swift").read_text()

        self.assertIn("startDownloadingUbiquitousItem", source)
        self.assertIn("CommandLine.arguments.dropFirst()", source)

        with tempfile.TemporaryDirectory() as temporary_directory:
            binary = pathlib.Path(temporary_directory) / "restic-icloud-download"
            compile_result = subprocess.run(
                ["xcrun", "swiftc", str(FILES / "restic-icloud-download.swift"), "-o", str(binary)],
                capture_output=True,
                check=False,
                text=True,
            )
            self.assertEqual(
                compile_result.returncode,
                0,
                compile_result.stdout + compile_result.stderr,
            )
            result = subprocess.run([str(binary)], capture_output=True, check=False, text=True)
            self.assertEqual(result.returncode, 64)

    def test_role_installs_and_compiles_download_helper(self) -> None:
        tasks = TASKS.read_text()

        self.assertIn("restic-icloud-download.swift", tasks)
        self.assertIn("xcrun swiftc", tasks)
        self.assertIn("restic-icloud-download.checksum", tasks)
        self.assertIn("restic-icloud-download.new", tasks)
        self.assertIn("restic_icloud_download_compiled_binary.stat.checksum is defined", tasks)
        self.assertIn('mode: \'0755\'', tasks)
        self.assertIn("restic-icloud-download", tasks)

    def test_excludes_unreadable_and_disposable_paths(self) -> None:
        template = (TEMPLATES / "exclude.j2").read_text()

        self.assertIn(
            "{{ home }}/Library/Group Containers/group.com.apple.CoreSpeech",
            template,
        )
        self.assertIn("{{ home }}/Library/Mobile Documents/.Trash", template)

    def test_restic_scripts_source_shared_cache_environment(self) -> None:
        for name in ("restic-s3-backup.j2", "restic-s3-check.j2"):
            with self.subTest(template=name):
                template = (TEMPLATES / name).read_text()
                self.assertIn(
                    'CACHE_ENV="{{ home }}/.config/environment/cache.sh"',
                    template,
                )
                self.assertIn('. "${CACHE_ENV}"', template)

    def test_role_preserves_shared_local_bin_permissions(self) -> None:
        tasks = TASKS.read_text()

        self.assertIn(
            '- path: "{{ ansible_facts[\'env\'][\'HOME\'] }}/.local/bin"\n      mode: \'0755\'',
            tasks,
        )

    def test_repository_initialization_sources_shared_cache_environment(self) -> None:
        tasks = TASKS.read_text()
        initialize_task = tasks.split('- name: "restic : Initialise the repository"', 1)[1]
        initialize_task = initialize_task.split('- name: "restic : Copy iCloud', 1)[0]

        self.assertIn('. "${HOME}/.config/environment/cache.sh"', initialize_task)
        self.assertLess(
            initialize_task.index('. "${HOME}/.config/environment/cache.sh"'),
            initialize_task.index("restic cat config"),
        )


if __name__ == "__main__":
    unittest.main()
