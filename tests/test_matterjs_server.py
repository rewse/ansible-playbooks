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


if __name__ == "__main__":
    unittest.main()
