#!/usr/bin/env python3
"""Regression tests for the zabbix_agent UserParameters."""

import os
import pathlib
import re
import subprocess
import tempfile
import unittest

FILES = pathlib.Path(__file__).resolve().parents[1] / "roles" / "zabbix_agent" / "files"

SMART_LOG = '{"critical_warning":0,"media_errors":0}'
# nvme-cli prints its error to stdout as JSON when given -o json.
ERROR_LOG = '{"error":"/dev/nvme0: No such file or directory"}'


def user_parameter(key, conf="raspberrypi.conf"):
    """Return the shell command a UserParameter runs for key."""
    prefix = f"UserParameter={key},"
    for line in (FILES / conf).read_text().splitlines():
        if line.startswith(prefix):
            return line[len(prefix) :]
    raise AssertionError(f"{key} is not defined")


def expand(command, *params):
    """Substitute positional references the way the agent does.

    The agent replaces $1 to $9 with the key parameters wherever they appear,
    including inside quotes, and turns $$ followed by a digit into $.
    """

    def replace(match):
        if match.group(1):
            return "$" + match.group(2)
        index = int(match.group(2)) - 1
        return params[index] if index < len(params) else ""

    return re.sub(r"\$(\$?)([1-9])", replace, command)


def run_with_fake(command, name, stdout, exit_code=0):
    """Run command with a name on PATH that prints stdout and exits."""
    with tempfile.TemporaryDirectory() as bin_dir:
        fake = pathlib.Path(bin_dir) / name
        fake.write_text(f"#!/bin/sh\nprintf '%s\\n' '{stdout}'\nexit {exit_code}\n")
        fake.chmod(0o755)
        env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"}
        return subprocess.run(
            ["sh", "-c", command], capture_output=True, text=True, env=env, check=False
        ).stdout


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
        output = run_with_fake(user_parameter("nvme.smart_log"), "nvme", SMART_LOG, 0)
        self.assertEqual(output.strip(), SMART_LOG)

    def test_prints_nothing_when_the_device_cannot_be_read(self):
        output = run_with_fake(user_parameter("nvme.smart_log"), "nvme", ERROR_LOG, 1)
        self.assertEqual(output, "")


# Two iostat -xk reports; the second, covering the last 5 s, is the one used.
IOSTAT = "nvme0n1 " + " ".join(["0"] * 19) + " 12.5"


class VfsDevUtilTest(unittest.TestCase):
    def run_key(self, device):
        command = expand(user_parameter("vfs.dev.util[*]", "ubuntu.conf"), device)
        return run_with_fake(command, "iostat", IOSTAT)

    def test_prints_the_utilization_of_the_device(self):
        self.assertEqual(self.run_key("nvme0n1").strip(), "12.5")

    def test_reads_no_file_named_in_the_parameter(self):
        with tempfile.TemporaryDirectory() as directory:
            # A line grep would print if it searched this file.
            data = pathlib.Path(directory) / "data"
            data.write_text(IOSTAT.replace("12.5", "99") + "\n")
            # A pattern that matches the iostat output if grep loaded it.
            patterns = pathlib.Path(directory) / "patterns"
            patterns.write_text("nvme0n1\n")
            for device in (f"nvme0n1 {data}", f"-f{patterns}"):
                with self.subTest(device=device):
                    self.assertEqual(self.run_key(device), "")


class ResticSuccessAgeTest(unittest.TestCase):
    def run_key(self, instance):
        command = expand(user_parameter("restic.success_age[*]"), instance)
        return subprocess.run(
            ["sh", "-c", command], capture_output=True, text=True, check=False
        ).stdout

    def test_reports_an_age_for_a_unit_instance(self):
        self.assertRegex(self.run_key("restic-s3-check-archive"), r"^\d+\n$")

    def test_prints_nothing_for_a_path(self):
        for instance in ("../../etc/passwd", "a/b", "..", "restic..x", ""):
            with self.subTest(instance=instance):
                self.assertEqual(self.run_key(instance), "")
