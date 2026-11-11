#!/usr/bin/env python3
"""Regression tests for the zabbix_aws CloudFront and WAF collector."""

import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
from datetime import UTC
from datetime import datetime

FILES = pathlib.Path(__file__).resolve().parents[1] / "roles" / "zabbix_aws" / "files"

NOW = 1794092400 + 700  # 2026-11-08 08:11:40 JST, inside a bucket
BUCKET = (NOW // 300) * 300 - 600


def iso(epoch):
    return datetime.fromtimestamp(epoch, UTC).isoformat()


FAKE_AWS = """\
import json, os, sys
args = sys.argv[1:]
# Each call advances the fake clock, as a slow AWS CLI would.
clock = os.environ["FAKE_CLOCK"]
elapsed = int(open(clock).read()) if os.path.exists(clock) else 0
with open(clock, "w") as f:
    f.write(str(elapsed + int(os.environ["AWS_CALL_SECONDS"])))
if "describe-stacks" in args:
    print("E123")
    sys.exit(0)
queries = args[args.index("--metric-data-queries") + 1].removeprefix("file://")
with open(queries) as f:
    ids = [q["Id"] for q in json.load(f)]
if ids and all(i.startswith("bucket_") for i in ids):
    window = [args[args.index("--start-time") + 1], args[args.index("--end-time") + 1]]
    with open(os.environ["BUCKET_WINDOW"], "w") as f:
        json.dump(window, f)
    sys.stdout.write(os.environ["BUCKET_ROWS"])
else:
    sys.stdout.write(os.environ["LATEST_ROWS"])
"""

FAKE_DATE = """\
import os, sys
from datetime import datetime, timezone
clock = os.environ["FAKE_CLOCK"]
now = int(os.environ["FAKE_NOW"])
now += int(open(clock).read()) if os.path.exists(clock) else 0
args = sys.argv[1:]
if args == ["+%s"]:
    print(now)
    sys.exit(0)
epoch = now
if "--date" in args:
    when = args[args.index("--date") + 1]
    epoch = int(when[1:]) if when.startswith("@") else now - 600
print(datetime.fromtimestamp(epoch, timezone.utc).isoformat())
"""

FAKE_SENDER = """\
import json, os, sys
with open(os.environ["SENDER_CALLS"], "a") as f:
    f.write(json.dumps({"args": sys.argv[1:], "input": sys.stdin.read()}) + "\\n")
"""


def first_bash(associative_arrays):
    """Returns the first bash in PATH that has or lacks associative arrays.

    cloudfront_waf.sh runs on the Linux hosts under bash 5. macOS ships bash
    3.2 as /bin/bash, where `declare -A` fails and every string subscript
    evaluates to index 0, so all metrics would collapse into the last one.
    Returns None when PATH holds no such bash.
    """
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        candidate = pathlib.Path(directory) / "bash"
        if not os.access(candidate, os.X_OK):
            continue
        probe = subprocess.run(
            [str(candidate), "-c", "declare -A probe"],
            capture_output=True,
            check=False,
        )
        if (probe.returncode == 0) == associative_arrays:
            return str(candidate)
    return None


BASH = first_bash(associative_arrays=True)
OLD_BASH = first_bash(associative_arrays=False)


class CollectorRun:
    def __init__(self, bucket_window, calls, process):
        self.bucket_window = bucket_window
        self.returncode = process.returncode
        self.stdout = process.stdout
        timestamped = [c for c in calls if "-T" in c["args"]]
        latest = [c for c in calls if "-T" not in c["args"]]
        self.timestamped_args = timestamped[0]["args"] if timestamped else None
        self.timestamped_input = timestamped[0]["input"] if timestamped else None
        self.latest_input = latest[0]["input"] if latest else None


def run_collector(bucket_rows, latest_rows="", aws_call_seconds=0, bash=BASH):
    """Run cloudfront_waf.sh with fake aws, date, and zabbix_sender."""
    assert bash is not None
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = pathlib.Path(tmp)
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        for name, body in (
            ("aws", FAKE_AWS),
            ("date", FAKE_DATE),
            ("zabbix_sender", FAKE_SENDER),
        ):
            fake = bin_dir / name
            fake.write_text(f"#!{sys.executable}\n{body}")
            fake.chmod(0o755)
        window_file = tmp_path / "window.json"
        calls_file = tmp_path / "calls.jsonl"
        env = {
            **os.environ,
            "AWS_CALL_SECONDS": str(aws_call_seconds),
            "BUCKET_ROWS": bucket_rows,
            "BUCKET_WINDOW": str(window_file),
            "FAKE_CLOCK": str(tmp_path / "clock"),
            "FAKE_NOW": str(NOW),
            "LATEST_ROWS": latest_rows,
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "SENDER_CALLS": str(calls_file),
            "TMPDIR": tmp,
        }
        process = subprocess.run(
            [bash, str(FILES / "cloudfront_waf.sh")],
            capture_output=True,
            env=env,
            text=True,
            check=False,
        )
        window = (
            tuple(json.loads(window_file.read_text())) if window_file.exists() else None
        )
        calls = (
            [json.loads(line) for line in calls_file.read_text().splitlines()]
            if calls_file.exists()
            else []
        )
        return CollectorRun(window, calls, process)


@unittest.skipUnless(BASH, "no bash with associative arrays in PATH")
class CloudfrontBucketTest(unittest.TestCase):
    def test_sends_bucket_requests_and_5xx_count(self):
        result = run_collector(
            "bucket_requests\t1996.0\nbucket_rate_5xx\t13.977955911823647\n"
        )
        self.assertIn("-T", result.timestamped_args or [])
        self.assertEqual(
            (result.timestamped_input or "").splitlines(),
            [
                f"- cloudfront.bucket.requests {BUCKET} 1996",
                f"- cloudfront.bucket.errors.5xx {BUCKET} 279",
            ],
        )

    def test_asks_for_exactly_the_bucket(self):
        result = run_collector("bucket_requests\t10.0\nbucket_rate_5xx\t0.0\n")
        self.assertEqual(result.bucket_window, (iso(BUCKET), iso(BUCKET + 300)))

    def test_bucket_is_fixed_before_the_first_request(self):
        # A slow AWS CLI must not move the bucket into the next five minutes,
        # which would skip one bucket and send the next twice.
        result = run_collector(
            "bucket_requests\t10.0\nbucket_rate_5xx\t0.0\n", aws_call_seconds=200
        )
        self.assertEqual(result.bucket_window, (iso(BUCKET), iso(BUCKET + 300)))

    def test_sends_nothing_without_bucket_data(self):
        result = run_collector("bucket_requests\tNone\nbucket_rate_5xx\tNone\n")
        self.assertIsNone(result.timestamped_input)

    def test_latest_values_are_still_sent(self):
        result = run_collector(
            "bucket_requests\t10.0\nbucket_rate_5xx\t0.0\n",
            latest_rows="mcloudfront_requests\t733.0\n",
        )
        self.assertIn("- cloudfront.requests 733.0", result.latest_input or "")


@unittest.skipUnless(OLD_BASH, "no bash without associative arrays in PATH")
class CloudfrontOldBashTest(unittest.TestCase):
    def test_refuses_to_run_without_associative_arrays(self):
        # Under bash 3.2 every key would collapse into one, so the script must
        # stop before it asks AWS for anything or sends a value.
        result = run_collector(
            "bucket_requests\t10.0\nbucket_rate_5xx\t0.0\n",
            latest_rows="mcloudfront_requests\t733.0\n",
            bash=OLD_BASH,
        )
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "1\n")
        self.assertIsNone(result.latest_input)
        self.assertIsNone(result.timestamped_input)


class CloudfrontWafTest(unittest.TestCase):
    def test_conf_defines_sender(self):
        text = (FILES / "cloudfront_waf.conf").read_text()
        self.assertIn("UserParameter=cloudfront_waf.sender,", text)

    def test_script_reads_us_east_1_and_web_acl(self):
        text = (FILES / "cloudfront_waf.sh").read_text()
        self.assertIn("readonly region=us-east-1", text)
        self.assertIn("readonly waf_acl=cloudfront-waf", text)

    def test_window_covers_two_periods_only(self):
        # A datapoint older than two periods is not resent, so a stalled metric
        # leaves the trapper item without new values instead of repeating one.
        text = (FILES / "cloudfront_waf.sh").read_text()
        self.assertIn("readonly period=300", text)
        self.assertIn("readonly window='10 minutes ago'", text)
