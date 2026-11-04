#!/usr/bin/env python3
"""Contract tests for the cloudfront_waf_report role."""

import configparser
import json
import pathlib
import re
import unittest

import jinja2
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
ROLE = REPO_ROOT / "roles" / "cloudfront_waf_report"


class SystemdUnit(configparser.ConfigParser):
    """Parse a systemd unit, whose keys are case-sensitive."""

    def optionxform(self, optionstr: str) -> str:
        return optionstr


def unit(path: pathlib.Path, text: str | None = None) -> configparser.ConfigParser:
    parser = SystemdUnit(interpolation=None, strict=False)
    parser.read_string(text if text is not None else path.read_text())
    return parser


def render(name: str, **values) -> str:
    environment = jinja2.Environment(
        undefined=jinja2.StrictUndefined, keep_trailing_newline=True
    )
    environment.filters["to_json"] = json.dumps
    return environment.from_string((ROLE / "templates" / name).read_text()).render(
        **values
    )


class RoleTest(unittest.TestCase):
    def test_timer_runs_on_saturday_morning(self):
        timer = unit(ROLE / "files" / "cloudfront-waf-report.timer")
        self.assertEqual(timer["Timer"]["OnCalendar"], "Sat *-*-* 07:47:00")
        self.assertEqual(timer["Timer"]["Persistent"], "true")
        self.assertEqual(timer["Install"]["WantedBy"], "timers.target")

    def test_service_runs_as_admin_user_and_notifies_failure(self):
        service = unit(
            ROLE / "templates" / "cloudfront-waf-report.service.j2",
            render("cloudfront-waf-report.service.j2", admin_user="tats"),
        )
        self.assertEqual(service["Service"]["User"], "tats")
        self.assertEqual(service["Service"]["Type"], "oneshot")
        self.assertEqual(
            service["Service"]["ExecStart"], "/usr/local/bin/cloudfront-waf-report"
        )
        self.assertEqual(service["Unit"]["OnFailure"], "failure-notify@%n.service")
        # A hung call must fail the unit so that OnFailure reports it.
        self.assertEqual(service["Service"]["TimeoutStartSec"], "2h")

    def test_config_template_renders_valid_json(self):
        accepted = [
            {
                "rule": "RateLimitLogin",
                "host": "hass.rewse.jp",
                "country": "JP",
                "reason": "ok",
            }
        ]
        config = json.loads(
            render(
                "config.json.j2",
                admin_user="tats",
                cloudfront_waf_report_accepted=accepted,
            )
        )
        self.assertEqual(
            config,
            {
                "recipient": "root",
                "state_dir": "/home/tats/.local/state/cloudfront-waf-report",
                "kiro_api_key_file": "/home/tats/.config/cloudfront-waf-report/kiro-api-key",
                "apache_log_dir": "/var/log/apache2",
                "accepted": accepted,
            },
        )

    def test_accepted_entries_hold_no_ip_addresses(self):
        text = (ROLE / "vars" / "main.yml").read_text()
        self.assertIsInstance(
            yaml.safe_load(text)["cloudfront_waf_report_accepted"], list
        )
        self.assertIsNone(re.search(r"\d{1,3}(?:\.\d{1,3}){3}", text))

    def test_tasks_install_script_config_and_timer(self):
        tasks = yaml.safe_load((ROLE / "tasks" / "main.yml").read_text())
        tags = [task["tags"] for task in tasks]
        self.assertEqual(
            tags, [["cloudfront_waf_report_script"], ["cloudfront_waf_report_timer"]]
        )
        script = yaml.safe_load((ROLE / "tasks" / "script.yml").read_text())
        dests = {
            task.get(
                "ansible.builtin.copy", task.get("ansible.builtin.template", {})
            ).get("dest")
            for task in script
        }
        self.assertIn("/usr/local/bin/cloudfront-waf-report", dests)
        self.assertIn("/etc/cloudfront-waf-report/config.json", dests)

    def test_role_is_in_home_primary(self):
        play = yaml.safe_load((REPO_ROOT / "home-primary.yml").read_text())[0]
        roles = [entry["role"] for entry in play["roles"]]
        self.assertIn("cloudfront_waf_report", roles)
        entry = next(
            entry for entry in play["roles"] if entry["role"] == "cloudfront_waf_report"
        )
        self.assertEqual(entry["tags"], ["cloudfront_waf_report"])


if __name__ == "__main__":
    unittest.main()
