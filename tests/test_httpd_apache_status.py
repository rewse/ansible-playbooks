#!/usr/bin/env python3
"""Regression tests for the httpd Zabbix server-status script."""

import os
import pathlib
import subprocess
import tempfile
import unittest

SCRIPT = (
    pathlib.Path(__file__).resolve().parents[1]
    / "roles"
    / "httpd"
    / "files"
    / "apache.sh"
)

# The HTML page lists each worker's client request line, which any client
# controls. A parser that greps the HTML page picks these up.
HTML_STATUS = """\
<dt>9 requests/sec - 99 kB/second - 9 B/request</dt>
<dt>99 requests currently being processed, 99 idle workers</dt>
<tr><td>GET /requests/sec HTTP/1.1</td></tr>
<tr><td>GET /x?a=B/second HTTP/1.1</td></tr>
<tr><td>GET /requests currently being processed HTTP/1.1</td></tr>
"""

AUTO_STATUS = """\
ServerVersion: Apache/2.4.58 (Ubuntu)
Total Accesses: 1234
Total kBytes: 5678
Uptime: 3600
ReqPerSec: .733
BytesPerSec: 6553.6
BytesPerReq: 8940.5
BusyWorkers: 2
IdleWorkers: 9
Fake ReqPerSec: 999
Scoreboard: __W_K____._
"""

FAKE_CURL = """\
#!/usr/bin/env python3
import os, sys
args = sys.argv[1:]
url = args[-1]
out = next(args[i + 1] for i, a in enumerate(args) if a.startswith("-") and a.endswith("o"))
with open(os.environ["CURL_CALLS"], "a") as f:
    f.write(url + "\\n")
with open(out, "w") as f:
    f.write(os.environ["AUTO_STATUS"] if url.endswith("?auto") else os.environ["HTML_STATUS"])
"""

FAKE_SENDER = """\
#!/usr/bin/env python3
import os, sys
args = sys.argv[1:]
with open(os.environ["SENDER_CALLS"], "a") as f:
    f.write(args[args.index("-k") + 1] + "=" + args[args.index("-o") + 1] + "\\n")
"""


def run_script(auto_status):
    """Run apache.sh with fake curl and zabbix_sender and return their calls."""
    with tempfile.TemporaryDirectory() as tmp:
        bin_dir = pathlib.Path(tmp)
        for name, body in (("curl", FAKE_CURL), ("zabbix_sender", FAKE_SENDER)):
            fake = bin_dir / name
            fake.write_text(body)
            fake.chmod(0o755)
        curl_calls = bin_dir / "curl_calls"
        sender_calls = bin_dir / "sender_calls"
        env = {
            **os.environ,
            "AUTO_STATUS": auto_status,
            "CURL_CALLS": str(curl_calls),
            "HTML_STATUS": HTML_STATUS,
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "SENDER_CALLS": str(sender_calls),
        }
        result = subprocess.run(
            ["bash", str(SCRIPT), "www.example.com"],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        urls = curl_calls.read_text().splitlines() if curl_calls.exists() else []
        sent = {}
        if sender_calls.exists():
            for line in sender_calls.read_text().splitlines():
                key, _, value = line.partition("=")
                sent[key] = value
        return result, urls, sent


class ApacheStatusTest(unittest.TestCase):
    def test_reads_the_machine_readable_status(self):
        _, urls, _ = run_script(AUTO_STATUS)
        self.assertEqual(urls, ["https://www.example.com/server-status?auto"])

    def test_sends_values_from_exact_keys(self):
        result, _, sent = run_script(AUTO_STATUS)
        self.assertEqual(result.stdout.strip(), "0")
        self.assertEqual(
            sent,
            {
                "apache.perf[byteps]": "6553.6",
                "apache.perf[reqps]": "0.733",
                "apache.proc.num[idle]": "9",
                "apache.proc.num[working]": "2",
            },
        )

    def test_omits_a_value_missing_from_the_status(self):
        status = "\n".join(
            line
            for line in AUTO_STATUS.splitlines()
            if not line.startswith("BytesPerSec:")
        )
        _, _, sent = run_script(status + "\n")
        self.assertNotIn("apache.perf[byteps]", sent)
        self.assertEqual(sent["apache.perf[reqps]"], "0.733")


if __name__ == "__main__":
    unittest.main()
