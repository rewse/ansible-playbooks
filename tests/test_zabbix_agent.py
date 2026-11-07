#!/usr/bin/env python3
"""Regression tests for the zabbix_agent UserParameters."""

import os
import pathlib
import subprocess
import tempfile
import unittest

FILES = pathlib.Path(__file__).resolve().parents[1] / "roles" / "zabbix_agent" / "files"

SMART_LOG = '{"critical_warning":0,"media_errors":0}'
# nvme-cli prints its error to stdout as JSON when given -o json.
ERROR_LOG = '{"error":"/dev/nvme0: No such file or directory"}'


def user_parameter(key):
    """Return the shell command a UserParameter runs for key."""
    prefix = f"UserParameter={key},"
    for line in (FILES / "raspberrypi.conf").read_text().splitlines():
        if line.startswith(prefix):
            return line[len(prefix) :]
    raise AssertionError(f"{key} is not defined")


def run_with_fake_nvme(command, stdout, exit_code):
    """Run command with an nvme on PATH that prints stdout and exits."""
    with tempfile.TemporaryDirectory() as bin_dir:
        fake = pathlib.Path(bin_dir) / "nvme"
        fake.write_text(f"#!/bin/sh\necho '{stdout}'\nexit {exit_code}\n")
        fake.chmod(0o755)
        env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"}
        return subprocess.run(
            ["sh", "-c", command], capture_output=True, text=True, env=env, check=False
        ).stdout


class NvmeSmartLogTest(unittest.TestCase):
    def test_reads_the_smart_log_as_json(self):
        self.assertIn(
            "nvme smart-log /dev/nvme0 -o json", user_parameter("nvme.smart_log")
        )

    def test_prints_the_smart_log_on_success(self):
        output = run_with_fake_nvme(user_parameter("nvme.smart_log"), SMART_LOG, 0)
        self.assertEqual(output.strip(), SMART_LOG)

    def test_prints_nothing_when_the_device_cannot_be_read(self):
        output = run_with_fake_nvme(user_parameter("nvme.smart_log"), ERROR_LOG, 1)
        self.assertEqual(output, "")
