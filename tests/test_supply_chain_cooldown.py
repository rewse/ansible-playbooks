#!/usr/bin/env python3
"""Regression tests for scheduled jobs that install from PyPI as root."""

import pathlib
import re
import subprocess
import unittest

import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
ROLES = REPO_ROOT / "roles"


def tracked_files(directory: pathlib.Path) -> list[pathlib.Path]:
    # Ignored files such as Finder's binary .DS_Store are never deployed, and
    # reading them as text fails.
    listing = subprocess.run(
        ["git", "ls-files", "-z", "--", str(directory)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [REPO_ROOT / name for name in sorted(listing.split("\0")) if name]


CUTOFF = re.compile(
    r"(?m)^UV_EXCLUDE_NEWER=\"\$\(date -u -d '"
    r"(?:\{\{|\[%) supply_chain_cooldown_days (?:\}\}|%\]) days ago' "
    r"\+%Y-%m-%dT%H:%M:%SZ\)\"\nexport UV_EXCLUDE_NEWER$"
)
UV_CALL = re.compile(r"(?m)^(?!\s*#).*\buvx? ")


def template_task(tasks_file: pathlib.Path, dest: str) -> dict:
    tasks = yaml.safe_load(tasks_file.read_text())
    return next(
        t["ansible.builtin.template"]
        for t in tasks
        if t.get("ansible.builtin.template", {}).get("dest") == dest
    )


class TimerCooldownTest(unittest.TestCase):
    def assert_cooldown_precedes_uv(self, script: pathlib.Path):
        # The timer runs between playbook runs, so the cutoff that
        # supply_chain_cooldown_environment gives a task is computed in the
        # script on each run instead.
        text = script.read_text()
        cutoff = CUTOFF.search(text)
        self.assertIsNotNone(cutoff, "no UV_EXCLUDE_NEWER cutoff")
        assert cutoff is not None
        calls = [m.start() for m in UV_CALL.finditer(text)]
        self.assertTrue(calls, "no uv call")
        self.assertLess(cutoff.end(), min(calls))

    def test_certbot_renew_applies_the_cooldown(self):
        role = ROLES / "sslcert"
        task = template_task(
            role / "tasks" / "certbot.yml", "/usr/local/sbin/certbot-renew"
        )
        self.assertEqual(task["src"], "certbot-renew.j2")
        self.assertFalse((role / "files" / "certbot-renew").exists())
        self.assert_cooldown_precedes_uv(role / "templates" / "certbot-renew.j2")

    def test_enecoq_data_fetcher_applies_the_cooldown(self):
        role = ROLES / "enecoq_data_fetcher"
        script = role / "templates" / "enecoq-data-fetcher.j2"
        self.assert_cooldown_precedes_uv(script)
        # The package is this account's own and is adopted without a cooldown;
        # its third-party dependencies, such as playwright, are not.
        for line in script.read_text().splitlines():
            if re.match(r"\s*uvx ", line):
                with self.subTest(line=line):
                    self.assertIn('--exclude-newer-package "$OWN_PACKAGE"', line)


class GitToolPinTest(unittest.TestCase):
    TASKS = ROLES / "ubuntu" / "tasks" / "uv.yml"
    REPO = "aws-samples/sample-agentcore-websearch-agent-skill"

    def test_git_tool_installs_an_aged_commit(self):
        tasks = yaml.safe_load(self.TASKS.read_text())
        commands = [
            task["ansible.builtin.command"]
            for task in tasks
            if "ansible.builtin.command" in task
        ]
        items = [item for task in tasks for item in task.get("loop", [])]
        self.assertEqual(
            [c for c in commands + items if "git+" in c],
            [
                (
                    f"uv tool install git+https://github.com/{self.REPO}"
                    "@{{ __ubuntu_agentcore_websearch.commit }}"
                )
            ],
        )
        lookups = [
            value
            for task in tasks
            for value in task.get("ansible.builtin.set_fact", {}).values()
        ]
        self.assertIn(
            f"{{{{ lookup('aged_release', 'github-commit:{self.REPO}', branch='main') }}}}",
            lookups,
        )


class DefaultBranchPinTest(unittest.TestCase):
    """A repository lookup names the default branch it expects to follow."""

    LOOKUP = re.compile(r"lookup\('aged_release', 'github-(?:tag|commit):[^']+'[^)]*\)")

    def test_every_branch_lookup_names_its_branch(self):
        calls = [
            (path.relative_to(REPO_ROOT).as_posix(), call.group(0))
            for path in tracked_files(REPO_ROOT / "roles")
            if path.suffix in (".yml", ".j2")
            for call in self.LOOKUP.finditer(path.read_text())
        ]
        self.assertTrue(calls)
        for path, call in calls:
            with self.subTest(path=path, call=call):
                self.assertRegex(call, r", branch='[^']+'")


class ZinitPinTest(unittest.TestCase):
    """zinit is sourced by root's shell, so it is checked out at an aged tag."""

    TASKS = ROLES / "ubuntu" / "tasks" / "zinit.yml"

    def setUp(self):
        self.text = self.TASKS.read_text()
        self.tasks = yaml.safe_load(self.text)

    def test_no_installer_or_self_update(self):
        self.assertNotRegex(self.text, r"curl[^\n]*\|\s*(?:ba)?sh|bash -c \"\$\(curl")
        self.assertNotIn("self-update", self.text)
        self.assertNotIn("ansible.builtin.shell", self.text)
        self.assertNotIn("ansible.builtin.command", self.text)

    def test_checkout_is_the_aged_tag_commit(self):
        lookups = [
            value
            for task in self.tasks
            for value in task.get("ansible.builtin.set_fact", {}).values()
        ]
        lookup = (
            "{{ lookup('aged_release', 'github-tag:zdharma-continuum/zinit',"
            " branch='main') }}"
        )
        self.assertEqual(lookups, [lookup])
        git = next(
            t["ansible.builtin.git"] for t in self.tasks if "ansible.builtin.git" in t
        )
        # The installer cloned this URL, so existing checkouts keep their origin.
        self.assertEqual(git["repo"], "https://github.com/zdharma-continuum/zinit")
        self.assertEqual(git["dest"], "/usr/local/share/zinit/zinit.git")
        self.assertEqual(git["version"], "{{ __ubuntu_zinit.commit }}")

    def test_component_keeps_the_update_tag(self):
        main = yaml.safe_load((ROLES / "ubuntu" / "tasks" / "main.yml").read_text())
        task = next(
            t for t in main if t.get("ansible.builtin.import_tasks") == "zinit.yml"
        )
        self.assertIn("update", task["tags"])


class CouchdbInitScriptTest(unittest.TestCase):
    """The LiveSync init script runs with the CouchDB admin password."""

    ROLE = ROLES / "couchdb"
    RAW = "https://raw.githubusercontent.com/vrtmrz/obsidian-livesync/"
    # couchdb-init.sh finds provision.ts beside itself and the Deno lockfile
    # and config in ../flyio, so the files keep the upstream layout.
    FILES = frozenset(
        {
            "couchdb/couchdb-init.sh",
            "couchdb/livesync-commonlib.ts",
            "couchdb/provision.ts",
            "flyio/deno.jsonc",
            "flyio/deno.lock",
        }
    )

    def setUp(self):
        self.vars = yaml.safe_load((self.ROLE / "vars" / "main.yml").read_text())
        self.tasks = yaml.safe_load((self.ROLE / "tasks" / "database.yml").read_text())
        self.handlers = yaml.safe_load(
            (self.ROLE / "handlers" / "main.yml").read_text()
        )
        self.base = self.vars["couchdb_livesync_dir"] + "/utils"

    def expand(self, text: str) -> str:
        return text.replace(
            "{{ couchdb_livesync_dir }}", self.vars["couchdb_livesync_dir"]
        )

    def test_role_never_names_an_upstream_branch(self):
        branch = re.compile(r"obsidian-livesync/(?:refs/heads/)?(?:main|master)\b")
        for path in tracked_files(self.ROLE):
            with self.subTest(path=path.relative_to(self.ROLE).as_posix()):
                self.assertIsNone(branch.search(path.read_text()))

    def test_files_come_from_the_pinned_commit(self):
        fetch = next(t for t in self.tasks if "ansible.builtin.uri" in t)
        self.assertEqual(
            fetch["ansible.builtin.uri"]["url"],
            self.RAW + "{{ __couchdb_livesync.commit }}/utils/{{ item }}",
        )
        self.assertEqual(fetch["loop"], "{{ couchdb_livesync_files }}")
        self.assertEqual(set(self.vars["couchdb_livesync_files"]), self.FILES)

    def test_files_keep_the_upstream_layout(self):
        install = next(t for t in self.tasks if "ansible.builtin.copy" in t)
        self.assertEqual(
            self.expand(install["ansible.builtin.copy"]["dest"]),
            self.base + "/{{ item.item }}",
        )

    def test_handler_runs_the_local_provision_script(self):
        handler = next(
            h for h in self.handlers if h["name"] == "Run couchdb init script"
        )
        self.assertEqual(
            self.expand(handler["ansible.builtin.command"]),
            self.base + "/couchdb/couchdb-init.sh",
        )
        # The script falls back to this URL when provision.ts is not beside it,
        # so a local path makes a missing copy fail instead of fetching upstream.
        self.assertEqual(
            self.expand(handler["environment"]["provision_script_url"]),
            self.base + "/couchdb/provision.ts",
        )


if __name__ == "__main__":
    unittest.main()
