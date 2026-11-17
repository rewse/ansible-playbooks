#!/usr/bin/env python3
"""Regression tests for the Home Assistant sensors fed by IMAP messages."""

import datetime
import pathlib
import re
import unittest
from typing import ClassVar

import jinja2
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
FILES = REPO_ROOT / "roles" / "homeassistant" / "files"

# The sensor each sender feeds, and the domain whose DKIM signature proves it.
SENDERS = {
    "e-ask@orico.co.jp": ("sensor.hills_card", "orico.co.jp"),
    "info@mamorail.jp": ("sensor.mamorail", "mamorail.jp"),
    "miwada_studyroom@outlook.com": ("sensor.mll", "outlook.com"),
    "thanks@aplus.co.jp": ("sensor.aplus", "aplus.co.jp"),
}


def regex_search(value, find="", ignorecase=False):
    """Home Assistant's regex_search filter."""
    flags = re.IGNORECASE if ignorecase else 0
    return bool(re.compile(find, flags).search(str(value)))


def environment() -> jinja2.Environment:
    env = jinja2.Environment(undefined=jinja2.StrictUndefined)
    env.filters["regex_search"] = regex_search
    return env


def mail_blocks() -> dict[str, dict]:
    groups = yaml.safe_load((FILES / "templates.yaml").read_text())
    return {
        group["triggers"][0]["event_data"]["sender"]: group
        for group in groups
        if group.get("triggers")
        and group["triggers"][0].get("event_type") == "imap_content"
    }


def arc(top: str, *lower: str) -> list[str]:
    """ARC-Authentication-Results values, topmost first, folded as Sakura writes them."""
    return [value.replace("\n", "\r\n    ") for value in (top, *lower)]


def sakura(instance: int, domain: str, verdict: str = "pass") -> str:
    return (
        f"i={instance}; rewse.jp;\n"
        "spf=pass smtp.mailfrom=bounce@mail.example smtp.helo=mta.mail.example;\n"
        f"dkim={verdict} (good signature) header.d={domain} header.s=s1 header.i=@{domain};\n"
        "arc=none;"
    )


class MailSensorTest(unittest.TestCase):
    def test_every_gated_sender_has_one_block(self):
        self.assertEqual(sorted(mail_blocks()), sorted(SENDERS))

    def test_mail_sensor_keeps_only_attributes_something_reads(self):
        for sender, block in mail_blocks().items():
            sensor = block["sensor"][0]
            with self.subTest(sender=sender):
                self.assertEqual(sensor["unique_id"], SENDERS[sender][0])
                self.assertEqual(
                    sorted(sensor["attributes"]),
                    ["Date", "Message", "Sender", "Subject"],
                )


class MailAuthenticationGateTest(unittest.TestCase):
    def accepts(self, sender: str, headers: dict) -> bool:
        block = mail_blocks()[sender]
        conditions = block.get("conditions", [])
        self.assertTrue(conditions, sender)
        trigger = {"event": {"data": {"sender": sender, "headers": headers}}}
        results = []
        for condition in conditions:
            self.assertEqual(condition["condition"], "template")
            text = (
                environment()
                .from_string(condition["value_template"])
                .render(trigger=trigger)
            )
            results.append(text.strip() == "True")
        return all(results)

    def test_accepts_sakura_dkim_pass_for_the_sender_domain(self):
        for sender, (_, domain) in SENDERS.items():
            with self.subTest(sender=sender):
                headers = {"ARC-Authentication-Results": arc(sakura(1, domain))}
                self.assertTrue(self.accepts(sender, headers))

    def test_accepts_a_forwarded_message_sakura_verified(self):
        headers = {
            "ARC-Authentication-Results": arc(
                sakura(3, "outlook.com"),
                "i=2; mx.google.com;\ndkim=pass header.i=@outlook.com",
                "i=1; mx.microsoft.com 1; dkim=none",
            )
        }
        self.assertTrue(self.accepts("miwada_studyroom@outlook.com", headers))

    def test_accepts_a_second_signature_beside_the_sender_domain(self):
        top = sakura(1, "mamorail.jp").replace(
            "arc=none;",
            "dkim=pass (good signature) header.d=ses.example header.s=s2;\narc=none;",
        )
        headers = {"ARC-Authentication-Results": arc(top)}
        self.assertTrue(self.accepts("info@mamorail.jp", headers))

    def test_rejects_messages_without_a_sakura_pass(self):
        sender, domain = "info@mamorail.jp", "mamorail.jp"
        cases = {
            "no header": {},
            "empty list": {"ARC-Authentication-Results": []},
            "dkim fail": {"ARC-Authentication-Results": arc(sakura(1, domain, "fail"))},
            "dkim none": {
                "ARC-Authentication-Results": arc(
                    "i=1; rewse.jp;\nspf=softfail smtp.mailfrom=x@evil.example;\ndkim=none;\narc=none;"
                )
            },
            "other domain": {
                "ARC-Authentication-Results": arc(sakura(1, "evil.example"))
            },
            "lookalike domain": {
                "ARC-Authentication-Results": arc(sakura(1, "mamorail.jp.evil.example"))
            },
            "parent domain only": {"ARC-Authentication-Results": arc(sakura(1, "jp"))},
            "other authserv-id on top": {
                "ARC-Authentication-Results": arc(
                    sakura(1, domain).replace("rewse.jp;", "mx.example;", 1)
                )
            },
            "lookalike authserv-id": {
                "ARC-Authentication-Results": arc(
                    sakura(1, domain).replace("rewse.jp;", "rewse.jp.evil.example;", 1)
                )
            },
            "pass only below Sakura's verdict": {
                "ARC-Authentication-Results": arc(
                    sakura(2, domain, "fail"), sakura(1, domain)
                )
            },
            "pass text inside the envelope sender": {
                "ARC-Authentication-Results": arc(
                    "i=1; rewse.jp;\n"
                    'spf=pass smtp.mailfrom="x; dkim=pass (good signature) '
                    f'header.d={domain} "@evil.example;\n'
                    "dkim=none;\narc=none;"
                )
            },
        }
        for name, headers in cases.items():
            with self.subTest(case=name):
                self.assertFalse(self.accepts(sender, headers))


class MailFreshnessTest(unittest.TestCase):
    NOW = datetime.datetime(2026, 11, 18, 12, 0, tzinfo=datetime.UTC)
    AUTOMATIONS: ClassVar[dict[str, str]] = {
        "automation.info_aplus": "sensor.aplus",
        "automation.info_hills_card": "sensor.hills_card",
        "automation.info_mamorail": "sensor.mamorail",
        "automation.info_mll": "sensor.mll",
    }

    def fresh(self, automation: dict, sensor: str, offset: int) -> bool:
        date = (self.NOW - datetime.timedelta(seconds=offset)).isoformat(sep=" ")
        env = environment()
        text = env.from_string(automation["conditions"][0]).render(
            now=lambda: self.NOW,
            as_timestamp=lambda value: (
                value
                if isinstance(value, datetime.datetime)
                else datetime.datetime.fromisoformat(value)
            ).timestamp(),
            state_attr=lambda entity, name: (
                date if (entity, name) == (sensor, "Date") else None
            ),
        )
        return text.strip() == "True"

    def test_only_a_recent_date_passes(self):
        automations = {
            automation["id"]: automation
            for automation in yaml.safe_load(
                (FILES / "automations-info.yaml").read_text()
            )
        }
        for automation_id, sensor in self.AUTOMATIONS.items():
            automation = automations[automation_id]
            for offset, expected in (
                (0, True),
                (30, True),
                (179, True),
                (180, False),
                (3600, False),
                (-30, True),
                (-60, False),
                (-86400, False),
            ):
                with self.subTest(automation=automation_id, offset=offset):
                    self.assertIs(self.fresh(automation, sensor, offset), expected)


if __name__ == "__main__":
    unittest.main()
