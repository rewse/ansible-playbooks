#!/usr/bin/env python3
"""Regression tests for the MH-Z19 MQTT publisher script."""

import os
import pathlib
import shutil
import subprocess
import tempfile
import textwrap
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
TEMPLATE = REPO_ROOT / "roles" / "mhz19" / "templates" / "mhz192mqtt.j2"


def find_gnu_grep() -> str | None:
    """Returns a grep that supports -P, or None when none is installed."""
    for name in ("grep", "ggrep"):
        path = shutil.which(name)
        if path is None:
            continue
        probe = subprocess.run(
            [path, "-oP", r"(?<=a)b"],
            input="ab",
            capture_output=True,
            check=False,
            text=True,
        )
        if probe.returncode == 0 and probe.stdout.strip() == "b":
            return path
    return None


GNU_GREP = find_gnu_grep()


@unittest.skipIf(GNU_GREP is None, "GNU grep with -P is not available")
class Mhz19PublisherTest(unittest.TestCase):
    def setUp(self) -> None:
        temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(temporary_directory.cleanup)
        self.root = pathlib.Path(temporary_directory.name)
        self.state_file = self.root / "state" / "state"

    def write_state(self, content: str) -> None:
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(content + "\n")

    @staticmethod
    def write_executable(path: pathlib.Path, content: str) -> None:
        path.write_text(content)
        path.chmod(0o755)

    def render(self, venv: pathlib.Path) -> str:
        template = TEMPLATE.read_text()
        # The venv path is replaced so a host with the real venv installed
        # still runs the fake python3.
        replacements = {
            "[% mhz19_location %]": "test_room",
            "[% mhz19_mosquitto_password %]": "secret",
            'VENV_PATH="/opt/mhz19"': f'VENV_PATH="{venv}"',
            "/var/lib/mhz19/state": str(self.state_file),
        }
        for source, destination in replacements.items():
            template = template.replace(source, destination)
        self.assertNotIn("[%", template)
        return template

    def run_publisher(
        self, outputs: list[str]
    ) -> tuple[subprocess.CompletedProcess[str], list[str], list[tuple[str, str]]]:
        run_dir = pathlib.Path(tempfile.mkdtemp(dir=self.root))
        bin_dir = run_dir / "bin"
        outputs_dir = run_dir / "outputs"
        calls = run_dir / "calls"
        published = run_dir / "published"
        counter = run_dir / "counter"
        bin_dir.mkdir()
        outputs_dir.mkdir()
        for index, output in enumerate(outputs):
            (outputs_dir / str(index)).write_text(output + "\n")
        counter.write_text("0")

        # Records its arguments and prints the next prepared sensor output.
        self.write_executable(
            bin_dir / "python3",
            textwrap.dedent(
                f"""\
                #!/bin/sh
                printf '%s\\n' "$*" >> '{calls}'
                n=$(cat '{counter}')
                echo $((n + 1)) > '{counter}'
                if [ -f '{outputs_dir}'/"$n" ]; then
                    cat '{outputs_dir}'/"$n"
                else
                    echo '{{}}'
                fi
                """
            ),
        )
        # Records the topic and message as one tab-separated line.
        self.write_executable(
            bin_dir / "mosquitto_pub",
            textwrap.dedent(
                f"""\
                #!/bin/sh
                topic=
                message=
                while [ $# -gt 0 ]; do
                    case "$1" in
                        -t) topic="$2"; shift 2 ;;
                        -m) message="$2"; shift 2 ;;
                        *) shift ;;
                    esac
                done
                printf '%s\\t%s\\n' "$topic" "$message" >> '{published}'
                """
            ),
        )
        self.write_executable(
            bin_dir / "date", "#!/bin/sh\necho 2026-01-01T00:00:00+09:00\n"
        )
        self.write_executable(bin_dir / "sleep", "#!/bin/sh\nexit 0\n")
        assert GNU_GREP is not None
        (bin_dir / "grep").symlink_to(GNU_GREP)

        script = run_dir / "mhz192mqtt"
        script.write_text(self.render(run_dir / "venv"))
        script.chmod(0o755)
        environment = os.environ.copy()
        environment["PATH"] = f"{bin_dir}:{environment['PATH']}"
        result = subprocess.run(
            [str(script)],
            capture_output=True,
            check=False,
            env=environment,
            text=True,
        )
        call_log = calls.read_text().splitlines() if calls.exists() else []
        published_log = []
        if published.exists():
            for line in published.read_text().splitlines():
                topic, message = line.split("\t", 1)
                published_log.append((topic, message))
        return result, call_log, published_log

    def test_reads_over_uart(self) -> None:
        result, calls, published = self.run_publisher(outputs=["{'co2': 650}"])

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(
            calls[0],
            "-m mh_z19 --serial_device /dev/ttyAMA0 --serial_console_untouched",
        )
        self.assertNotIn("--pwm", "\n".join(calls))
        self.assertTrue(
            any(t == "mhz19/test_room/co2" and '"co2":650' in m for t, m in published)
        )

    def test_uart_no_response_publishes_offline(self) -> None:
        result, calls, published = self.run_publisher(outputs=["{}", "{}", "{}"])

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(len(calls), 3)
        self.assertEqual(published[-1], ("mhz19/test_room/state", "offline"))

    def test_level_change_is_accepted_after_three_agreeing_readings(self) -> None:
        self.write_state("600 600 600 600")
        for expected_published in (False, False, True):
            result, _, published = self.run_publisher(outputs=["{'co2': 900}"])
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(
                any(t.endswith("/co2") for t, _ in published), expected_published
            )


if __name__ == "__main__":
    unittest.main()
