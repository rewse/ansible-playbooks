#!/usr/bin/env python3
"""Regression tests for the Home Assistant shell commands."""

import pathlib
import shlex
import unittest

import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
TEMPLATE = (
    REPO_ROOT / "roles" / "homeassistant" / "templates" / "shell_commands.yaml.j2"
)


def load_commands(text: str) -> dict[str, str]:
    # The first line is the ansible_managed comment in [% %] delimiters.
    body = "\n".join(line for line in text.splitlines() if not line.startswith("[%"))
    return yaml.safe_load(body)


class RegzaCommandTest(unittest.TestCase):
    def test_commands_end_with_a_clean_url(self):
        # Home Assistant runs these through a shell, so the shell's word
        # splitting decides what curl receives.
        commands = load_commands(TEMPLATE.read_text())
        regza = {
            name: command
            for name, command in commands.items()
            if name.endswith("_regza")
        }
        self.assertTrue(regza)
        for name, command in regza.items():
            with self.subTest(command=name):
                words = shlex.split(command)
                self.assertEqual(words[0], "curl")
                self.assertTrue(
                    words[-1].startswith(
                        "https://regza.rewse.jp:4430/remote/remote.htm?key="
                    )
                )
                self.assertFalse(any(word != word.strip() for word in words))


if __name__ == "__main__":
    unittest.main()
