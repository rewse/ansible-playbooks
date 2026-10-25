#!/usr/bin/env python3
"""Contract tests for the matterjs_server role."""

import pathlib
import unittest

import jinja2
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
ROLE = REPO_ROOT / "roles" / "matterjs_server"

NETWORKS = {
    "aws_private_ipv4": "10.0.0.0/16",
    "aws_public_ipv6": "2001:db8:aa::/56",
    "home_private_ipv4": "192.168.0.0/24",
    "home_private_ipv6": "fd00:db8::/64",
    "home_public_ipv4": "192.0.2.9/32",
    "home_public_ipv6": "2001:db8:bb::/64",
    "office_public_ipv4": ["198.51.100.0/24", "203.0.113.0/24"],
}


def role_vars() -> dict:
    return yaml.safe_load((ROLE / "vars" / "main.yml").read_text())


def load_tasks(name: str) -> list[dict]:
    return yaml.safe_load((ROLE / "tasks" / name).read_text())


def render(name: str, **overrides) -> str:
    environment = jinja2.Environment(
        loader=jinja2.FileSystemLoader(ROLE / "templates"),
        undefined=jinja2.StrictUndefined,
    )
    environment.filters["comment"] = lambda text: f"#\n# {text}\n#"
    context = {
        **role_vars(),
        "__matterjs_server_image": {
            "ref": "ghcr.io/matter-js/matterjs-server:1.5.5@sha256:" + "0" * 64
        },
        "ansible_managed": "Ansible managed",
        "networks": NETWORKS,
    }
    context.update(overrides)
    return environment.get_template(name).render(**context)


def handlers(role: pathlib.Path) -> dict:
    return {h["name"]: h for h in yaml.safe_load((role / "handlers" / "main.yml").read_text())}


class MatterjsServerRoleTest(unittest.TestCase):
    def test_ping_is_open_to_every_group(self):
        conf = (ROLE / "files" / "60-matterjs-server-ping.conf").read_text()
        self.assertRegex(conf, r"(?m)^net\.ipv4\.ping_group_range = 0 2147483647$")

    def test_sysctl_reload_matches_the_raspberrypi_role(self):
        theirs = handlers(REPO_ROOT / "roles" / "raspberrypi")
        self.assertEqual(handlers(ROLE)["Reload sysctl"], theirs["Reload sysctl"])

    def test_sysctl_drop_in_notifies_the_reload(self):
        task = load_tasks("sysctl.yml")[0]
        self.assertEqual(task["ansible.builtin.copy"]["dest"], "/etc/sysctl.d")
        self.assertEqual(task["notify"], "Reload sysctl")

    def test_sysctl_is_the_first_component(self):
        first = load_tasks("main.yml")[0]
        self.assertEqual(first["ansible.builtin.import_tasks"], "sysctl.yml")
        self.assertEqual(first["tags"], ["matterjs_server_sysctl"])


def compose() -> dict:
    return yaml.safe_load(render("compose.yaml.j2"))["services"]["matterjs-server"]


class MatterjsServerContainerTest(unittest.TestCase):
    def test_compose_project_and_service(self):
        project = yaml.safe_load(render("compose.yaml.j2"))
        self.assertEqual(project["name"], "matterjs_server")
        service = project["services"]["matterjs-server"]
        self.assertEqual(service["container_name"], "matterjs-server")
        self.assertEqual(service["network_mode"], "host")
        self.assertEqual(service["restart"], "unless-stopped")
        self.assertEqual(service["volumes"], ["/srv/matterjs_server/data:/data"])
        self.assertTrue(service["image"].startswith("ghcr.io/matter-js/matterjs-server:"))

    def test_environment_is_exactly_the_three_settings(self):
        self.assertEqual(
            compose()["environment"],
            {
                "LISTEN_ADDRESS": "127.0.0.1,::1",
                "PRIMARY_INTERFACE": "eth0",
                "PRODUCTION_MODE": "true",
            },
        )

    def test_no_bluetooth_or_extra_privileges(self):
        service = compose()
        for key in ("security_opt", "cap_add", "privileged", "user"):
            self.assertNotIn(key, service)
        self.assertNotIn("/run/dbus", render("compose.yaml.j2"))

    def test_start_is_guarded_by_migrated_or_python_data(self):
        tasks = {t["name"]: t for t in load_tasks("container.yml")}
        stats = {
            t["ansible.builtin.stat"]["path"]
            for t in tasks.values()
            if "ansible.builtin.stat" in t
        }
        self.assertLessEqual(
            {
                "{{ matterjs_server_data_dir }}/chip.json",
                "{{ matterjs_server_data_dir }}/server",
            },
            stats,
        )
        fail = tasks["container | Fail without data to migrate"]
        report = tasks["container | Report skipped start without data"]
        start = tasks["container | Start containers"]
        self.assertIn("not ansible_check_mode", str(fail["when"]))
        self.assertIn("ansible_check_mode", str(report["when"]))
        self.assertIn("__matterjs_server_chip.stat.exists", str(start["when"]))
        self.assertIn("__matterjs_server_storage.stat.exists", str(start["when"]))

    def test_data_directory_is_owned_by_the_container_user(self):
        task = next(
            t["ansible.builtin.file"]
            for t in load_tasks("container.yml")
            if t.get("ansible.builtin.file", {}).get("path") == "{{ matterjs_server_data_dir }}"
        )
        self.assertEqual((task["owner"], task["group"], task["mode"]), (1000, 1000, "0700"))
        self.assertNotIn("recurse", task)

    def test_legacy_removal_keeps_python_data(self):
        self.assertNotIn("/srv/matter_server", (ROLE / "tasks" / "container.yml").read_text())
        tasks = load_tasks("container.yml")
        removed = [
            t["ansible.builtin.file"]["path"]
            for t in tasks
            if t.get("ansible.builtin.file", {}).get("state") == "absent"
        ]
        self.assertEqual(removed, ["/etc/compose/matter_server"])
        down = next(
            t["community.docker.docker_compose_v2"]
            for t in tasks
            if t.get("community.docker.docker_compose_v2", {}).get("state") == "absent"
        )
        self.assertEqual(down["project_src"], "/etc/compose/matter_server")

    def test_container_is_an_update_component(self):
        imports = {t["ansible.builtin.import_tasks"]: t["tags"] for t in load_tasks("main.yml")}
        self.assertEqual(imports["container.yml"], ["matterjs_server_container", "update"])


if __name__ == "__main__":
    unittest.main()
