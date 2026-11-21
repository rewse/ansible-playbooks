#!/usr/bin/env python3
"""Regression tests for the enecoQ data fetcher role."""

import configparser
import json
import pathlib
import posixpath
import re
import shlex
import unittest
from typing import Any

import jinja2
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
ROLE = REPO_ROOT / "roles" / "enecoq_data_fetcher"
HOMEASSISTANT = REPO_ROOT / "roles" / "homeassistant"
TOGGLE = "enecoq_data_fetcher_timer_enabled"
UNIT = "/etc/systemd/system/enecoq-data-fetcher.service"


def load(path: str) -> Any:
    return yaml.safe_load((ROLE / path).read_text())


def named(path: str, name: str) -> dict[str, Any]:
    (entry,) = [e for e in load(path) if e["name"] == name]
    return entry


def resolved_vars() -> dict[str, Any]:
    """Return vars/main.yml with references between its values rendered."""
    raw = {
        key: value
        for key, value in load("vars/main.yml").items()
        if "lookup(" not in str(value)
    }
    environment = jinja2.Environment(undefined=jinja2.StrictUndefined)

    def render(value: Any, context: dict[str, Any]) -> Any:
        if isinstance(value, str):
            return environment.from_string(value).render(**context)
        if isinstance(value, dict):
            return {k: render(v, context) for k, v in value.items()}
        return value

    values = raw
    for _ in range(3):
        values = {key: render(value, values) for key, value in raw.items()}
    return values


VARS = resolved_vars()
USER = VARS["enecoq_data_fetcher_user"]
OUTPUT_DIR = VARS["enecoq_data_fetcher_output_dir"]


def render_template(name: str, start: str = "{{", end: str = "}}") -> str:
    environment = jinja2.Environment(
        loader=jinja2.FileSystemLoader(ROLE / "templates"),
        undefined=jinja2.StrictUndefined,
        keep_trailing_newline=True,
        trim_blocks=True,
        variable_start_string=start,
        variable_end_string=end,
    )
    environment.filters["comment"] = lambda text: f"#\n# {text}\n#"
    environment.filters["basename"] = posixpath.basename
    environment.filters["quote"] = shlex.quote
    return environment.get_template(name).render(
        ansible_managed="Ansible managed",
        enecoq_data_fetcher_enecoq={"email": "e", "password": "p"},
        supply_chain_cooldown_days=4,
        **VARS,
    )


def unit() -> configparser.SectionProxy:
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    parser.optionxform = str  # type: ignore[assignment]
    text = render_template("enecoq-data-fetcher.service.j2")
    parser.read_string(
        "\n".join(line for line in text.splitlines() if not line.startswith("#"))
    )
    return parser["Service"]


def unit_environment() -> dict[str, str]:
    text = render_template("enecoq-data-fetcher.service.j2")
    return dict(
        line.removeprefix("Environment=").split("=", 1)
        for line in text.splitlines()
        if line.startswith("Environment=")
    )


def script_output() -> str:
    text = render_template("enecoq-data-fetcher.j2", start="[%", end="%]")
    (match,) = re.findall(r"(?m)^readonly OUTPUT=(\S+)$", text)
    return match


class TimerToggleTest(unittest.TestCase):
    # One variable decides whether the timer runs, so a change to the timer unit
    # cannot start a timer that the variable keeps off.
    def test_toggle_is_a_boolean(self):
        self.assertIsInstance(load("vars/main.yml")[TOGGLE], bool)

    def test_timer_follows_the_toggle(self):
        task = named("tasks/service.yml", "service | Enable and start timer")
        systemd = task["ansible.builtin.systemd"]
        self.assertEqual(systemd["enabled"], "{{ " + TOGGLE + " }}")
        self.assertEqual(
            systemd["state"], "{{ 'started' if " + TOGGLE + " else 'stopped' }}"
        )

    def test_restart_handler_follows_the_toggle(self):
        handler = named("handlers/main.yml", "Restart enecoq-data-fetcher timer")
        self.assertEqual(handler.get("when"), TOGGLE)


class UnprivilegedServiceTest(unittest.TestCase):
    # The fetcher runs a browser on a third-party site and installs its
    # dependencies from PyPI on every run, so it runs as its own user and can
    # write only its caches and the file Home Assistant reads.
    def test_user_is_a_system_account_without_a_login(self):
        task = named("tasks/user.yml", "user | Create system user")
        user = task["ansible.builtin.user"]
        self.assertEqual(user["name"], "{{ enecoq_data_fetcher_user }}")
        self.assertIs(user["system"], True)
        self.assertEqual(user["shell"], "/usr/sbin/nologin")
        self.assertEqual(user["home"], "{{ enecoq_data_fetcher_home }}")

    def test_unit_runs_as_the_user(self):
        service = unit()
        self.assertEqual(service["User"], USER)
        self.assertEqual(service["Group"], USER)

    def test_unit_is_sandboxed(self):
        service = unit()
        for key, value in (
            ("NoNewPrivileges", "yes"),
            ("PrivateTmp", "yes"),
            ("ProtectHome", "yes"),
            ("ProtectSystem", "strict"),
            ("ReadWritePaths", OUTPUT_DIR),
        ):
            with self.subTest(key=key):
                self.assertEqual(service[key], value)

    def test_unit_directories_match_the_role(self):
        service = unit()
        self.assertEqual(
            "/var/lib/" + service["StateDirectory"], VARS["enecoq_data_fetcher_home"]
        )
        self.assertEqual(
            "/var/cache/" + service["CacheDirectory"],
            VARS["enecoq_data_fetcher_cache_dir"],
        )

    def test_caches_live_in_the_cache_directory(self):
        environment = unit_environment()
        self.assertEqual(set(environment), {"PLAYWRIGHT_BROWSERS_PATH", "UV_CACHE_DIR"})
        for name, path in environment.items():
            with self.subTest(name=name):
                self.assertTrue(
                    path.startswith(VARS["enecoq_data_fetcher_cache_dir"] + "/")
                )

    def test_unit_is_rendered_from_the_template(self):
        task = named("tasks/service.yml", "service | Install systemd service")
        template = task["ansible.builtin.template"]
        self.assertEqual(template["src"], "enecoq-data-fetcher.service.j2")
        self.assertEqual(template["dest"], UNIT)
        self.assertFalse((ROLE / "files" / "enecoq-data-fetcher.service").exists())

    def test_output_is_inside_the_writable_directory(self):
        self.assertEqual(posixpath.dirname(script_output()), OUTPUT_DIR)

    def test_output_directory_belongs_to_the_user(self):
        task = named("tasks/service.yml", "service | Create output directory")
        spec = task["ansible.builtin.file"]
        self.assertEqual(spec["path"], "{{ enecoq_data_fetcher_output_dir }}")
        self.assertEqual(spec["owner"], "{{ enecoq_data_fetcher_user }}")
        self.assertEqual(spec["group"], "{{ enecoq_data_fetcher_user }}")

    def test_script_is_readable_by_the_user_only(self):
        # The script holds the credentials; root owns it so the user cannot
        # change what the next run does, and the group lets the user run it.
        task = named("tasks/service.yml", "service | Install script")
        template = task["ansible.builtin.template"]
        self.assertEqual(template["owner"], "root")
        self.assertEqual(template["group"], "{{ enecoq_data_fetcher_user }}")
        self.assertEqual(template["mode"], "0750")


def home_assistant_mount(host_path: str) -> tuple[str, str]:
    """Return the container path of host_path and the options of its mount."""
    compose = (HOMEASSISTANT / "templates" / "compose.yaml.j2").read_text()
    volumes = re.findall(r"(?m)^\s+- (/[^:\s]+):(/[^:\s]+)(?::(\w+))?$", compose)
    for source, target, options in volumes:
        if host_path.startswith(source + "/"):
            return target + host_path[len(source) :], options
    raise AssertionError(f"{host_path} is not mounted into Home Assistant")


class HomeAssistantReadsTheOutputTest(unittest.TestCase):
    def test_sensors_read_the_file_the_fetcher_writes(self):
        sensors = yaml.safe_load(
            (HOMEASSISTANT / "files" / "command_lines.yaml").read_text()
        )
        commands = {
            entry["sensor"]["command"]
            for entry in sensors
            if "enecoq" in entry["sensor"]["unique_id"]
        }
        path, _ = home_assistant_mount(script_output())
        self.assertEqual(commands, {f"cat {path}"})

    def test_home_assistant_cannot_write_the_output(self):
        _, options = home_assistant_mount(script_output())
        self.assertEqual(options, "ro")

    def test_output_is_outside_the_home_assistant_tree(self):
        # The Home Assistant configuration is private to root, so the user could
        # not reach a directory inside it. A mount nested in /config would make
        # Docker create its mount point in that tree.
        self.assertFalse(OUTPUT_DIR.startswith("/srv/homeassistant/"))
        path, _ = home_assistant_mount(script_output())
        self.assertFalse(path.startswith("/config/"))

    def test_output_directory_cannot_be_swapped_for_a_link(self):
        # Docker follows a link at the bind source, so the directory sits in one
        # that only root can write.
        self.assertEqual(posixpath.dirname(OUTPUT_DIR), "/srv")


class BrowserInstallTest(unittest.TestCase):
    TASK = "browser | Install Chromium with Playwright"

    def test_runs_as_the_user_with_the_unit_environment(self):
        task = named("tasks/browser.yml", self.TASK)
        self.assertIs(task["become"], True)
        self.assertEqual(task["become_user"], "{{ enecoq_data_fetcher_user }}")
        self.assertEqual(
            task["environment"],
            "{{ supply_chain_cooldown_environment"
            " | combine(enecoq_data_fetcher_environment) }}",
        )
        self.assertEqual(VARS["enecoq_data_fetcher_environment"], unit_environment())

    def test_installs_the_browser_of_the_fetcher(self):
        # The Playwright release the fetcher depends on decides which Chromium
        # build it launches, so the install goes through the same package.
        command = named("tasks/browser.yml", self.TASK)["ansible.builtin.command"]
        self.assertIn("--from enecoq-data-fetcher@latest", command["cmd"])
        self.assertIn("playwright install chromium", command["cmd"])
        self.assertIn("--exclude-newer-package enecoq-data-fetcher=", command["cmd"])
        self.assertNotIn("npx", command["cmd"])


class OutputDirectoryTest(unittest.TestCase):
    def tasks(self) -> list[dict[str, Any]]:
        return [
            task
            for path in ("tasks/service.yml", "tasks/user.yml")
            for task in load(path)
        ]

    def test_output_directory_does_not_follow_links(self):
        task = named("tasks/service.yml", "service | Create output directory")
        self.assertIs(task["ansible.builtin.file"]["follow"], False)

    def test_root_leaves_the_files_of_the_user_alone(self):
        # The user can replace its files with links, so a root task on one of
        # them would act on whatever the link points to.
        for task in self.tasks():
            module = next((key for key in task if key.startswith("ansible.")), "")
            spec = task.get(module)
            if not isinstance(spec, dict):
                continue
            target = str(spec.get("path", spec.get("dest", spec.get("src", ""))))
            with self.subTest(task=task["name"]):
                self.assertFalse(
                    target.startswith("{{ enecoq_data_fetcher_output_dir }}/")
                )

    def test_role_stays_out_of_the_home_assistant_tree(self):
        for task in self.tasks():
            spec = task.get("ansible.builtin.file") or task.get("ansible.builtin.copy")
            if spec is None or spec.get("state") == "absent":
                continue
            with self.subTest(task=task["name"]):
                self.assertNotIn("/srv/homeassistant", json.dumps(spec))

    def test_new_output_directory_starts_a_fetch(self):
        # Home Assistant's sensors would otherwise have no file until the timer.
        task = named("tasks/service.yml", "service | Create output directory")
        self.assertEqual(task.get("notify"), "Start enecoq-data-fetcher")
        handler = named("handlers/main.yml", "Start enecoq-data-fetcher")
        systemd = handler["ansible.builtin.systemd"]
        self.assertEqual(systemd["name"], "enecoq-data-fetcher.service")
        self.assertEqual(systemd["state"], "started")
        # A fetch takes minutes and depends on enecoQ, so the run does not wait.
        self.assertIs(systemd["no_block"], True)


class LegacyStateTest(unittest.TestCase):
    def removed(self) -> list[str]:
        return [
            path
            for t in load("tasks/service.yml")
            if t.get("ansible.builtin.file", {}).get("state") == "absent"
            for path in t.get("loop", [t["ansible.builtin.file"]["path"]])
        ]

    def test_old_output_directory_is_removed(self):
        self.assertIn("/srv/homeassistant/config/data", self.removed())

    def test_old_root_checkout_is_removed(self):
        self.assertIn("/opt/enecoq-fetch", self.removed())


if __name__ == "__main__":
    unittest.main()
