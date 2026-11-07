#!/usr/bin/env python3
"""Regression tests for the zabbix_agent UserParameters."""

import pathlib
import unittest

FILES = pathlib.Path(__file__).resolve().parents[1] / "roles" / "zabbix_agent" / "files"


class RaspberrypiConfTest(unittest.TestCase):
    def test_nvme_smart_log_returns_json_and_nothing_on_failure(self):
        # stderr is discarded so an unreadable device yields empty output,
        # which marks the item unsupported instead of reporting false data.
        text = (FILES / "raspberrypi.conf").read_text()
        self.assertIn(
            "UserParameter=nvme.smart_log,nvme smart-log /dev/nvme0 -o json 2>/dev/null\n",
            text,
        )
