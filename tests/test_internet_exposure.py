#!/usr/bin/env python3
"""Regression tests for services the internet reaches through Apache."""

import configparser
import importlib.util
import pathlib
import re
import subprocess
import tempfile
import time
import unittest
from typing import ClassVar

import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
ROLES = REPO_ROOT / "roles"
AUTODISCOVER = ROLES / "autodiscover"
FAIL2BAN = ROLES / "fail2ban"
FILEBROWSER = ROLES / "filebrowser"
HTTPD = ROLES / "httpd"
HOMEASSISTANT = ROLES / "homeassistant"
NVR = ROLES / "nvr"
POSTFIX_CLIENT = ROLES / "postfix_client"
SECONDARY = ROLES / "homeassistant_ha_secondary"
TESLAMATE = ROLES / "teslamate"
UDM = ROLES / "udm"


def load_yaml(path: pathlib.Path):
    return yaml.safe_load(path.read_text())


def jail(path: pathlib.Path, section: str) -> configparser.SectionProxy:
    parser = configparser.ConfigParser(interpolation=None)
    lines = [
        line
        for line in path.read_text().splitlines()
        if not line.lstrip().startswith(("#", "{{"))
    ]
    parser.read_string("\n".join(lines))
    return parser[section]


def filter_regex(path: pathlib.Path, variable: str, hostname: str) -> re.Pattern:
    text = path.read_text()
    line = next(line for line in text.splitlines() if line.startswith("failregex = "))
    pattern = line.removeprefix("failregex = ")
    pattern = pattern.replace(
        "{{ " + variable + " | regex_escape }}", re.escape(hostname)
    )
    pattern = pattern.replace("<HOST>", r"(?P<host>\S+)")
    return re.compile(pattern)


def access_line(vhost: str, request: str, status: int) -> str:
    # A vhost_combined line as fail2ban sees it, with the timestamp removed.
    return f'{vhost}:443 203.0.113.7 - - [] "{request} HTTP/1.1" {status} 28 "-" "curl"'


class NvrFail2banTest(unittest.TestCase):
    def test_fail2ban_component_is_imported(self):
        imports = {
            task["ansible.builtin.import_tasks"]: task["tags"]
            for task in load_yaml(NVR / "tasks" / "main.yml")
        }
        self.assertEqual(imports.get("fail2ban.yml"), ["nvr_fail2ban"])
        roles = [
            dep["role"] for dep in load_yaml(NVR / "meta" / "main.yml")["dependencies"]
        ]
        self.assertIn("fail2ban", roles)

    def test_jail_reads_the_apache_log(self):
        section = jail(NVR / "templates" / "fail2ban-jail.conf.j2", "nvr")
        self.assertEqual(section["enabled"], "true")
        self.assertEqual(section["backend"], "auto")
        self.assertEqual(section["filter"], "nvr")
        self.assertEqual(section["logpath"], "/var/log/apache2/other_vhosts_access.log")

    def test_filter_matches_failed_frigate_logins_only(self):
        hostname = load_yaml(NVR / "vars" / "main.yml")["nvr_hostname"]
        self.assertEqual(hostname, "nvr.rewse.jp")
        regex = filter_regex(
            NVR / "templates" / "fail2ban-filter.conf.j2", "nvr_hostname", hostname
        )
        failed = access_line("nvr.rewse.jp", "POST /api/login", 401)
        match = regex.search(failed)
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match["host"], "203.0.113.7")
        for line in (
            # A successful login.
            access_line("nvr.rewse.jp", "POST /api/login", 200),
            # A failed login on another virtual host.
            access_line("nas.rewse.jp", "POST /api/login", 401),
            # An expired session polling the API.
            access_line("nvr.rewse.jp", "GET /api/profile", 401),
        ):
            with self.subTest(line=line):
                self.assertIsNone(regex.search(line))


class StandbyHomeAssistantFail2banTest(unittest.TestCase):
    LOG = "/srv/homeassistant/config/home-assistant.log"

    def test_jail_is_always_enabled(self):
        # The standby serves hass.rewse.jp during a failover, and the jail has to
        # be running by then; a run cannot be counted on to happen in between.
        section = jail(
            HOMEASSISTANT / "templates" / "fail2ban-jail.conf.j2", "homeassistant"
        )
        self.assertEqual(section["enabled"], "true")
        self.assertEqual(section["logpath"], self.LOG)
        text = (SECONDARY / "tasks" / "fail2ban.yml").read_text()
        self.assertNotIn("homeassistant_fail2ban_enabled", text)
        self.assertNotIn("ansible.builtin.stat", text)

    def test_standby_creates_the_log_the_jail_reads(self):
        # homeassistant-sync excludes *.log*, so the log exists only if the
        # standby makes it, and rsync --delete leaves excluded files alone.
        self.assertIn(
            "--exclude='*.log*'",
            (SECONDARY / "files" / "homeassistant-sync").read_text(),
        )
        tasks = load_yaml(SECONDARY / "tasks" / "fail2ban.yml")
        touch = next(
            t["ansible.builtin.file"]
            for t in tasks
            if t.get("ansible.builtin.file", {}).get("path") == self.LOG
        )
        self.assertEqual(touch["state"], "touch")
        self.assertEqual(touch["access_time"], "preserve")
        self.assertEqual(touch["modification_time"], "preserve")


class HomeAssistantNameSwitchTest(unittest.TestCase):
    def test_name_switch_moves_only_the_https_forward(self):
        # CloudFront fronts the services and WAN port 80 is closed, so the failover
        # moves only the 443 forward.
        text = (SECONDARY / "templates" / "homeassistant-name-switch.j2").read_text()
        self.assertIn("FORWARDED_PORTS=(443)", text)
        self.assertNotIn("forward of 80", text)
        self.assertNotIn("FORWARDED_PORTS=(443 80)", text)


class FileBrowserForwardedForTest(unittest.TestCase):
    def test_vhost_drops_client_forwarded_for(self):
        # FileBrowser trusts X-Forwarded-For for its lockout and audit log, and
        # mod_proxy appends to a header the client sent rather than replacing it.
        # The unset runs in fixups, after mod_remoteip restores the client
        # address; an early unset races mod_remoteip in post_read_request.
        text = (FILEBROWSER / "templates" / "nas.rewse.jp.conf.j2").read_text()
        self.assertRegex(text, r"(?m)^\s*RequestHeader unset X-Forwarded-For$")
        self.assertNotRegex(text, r"(?m)^\s*RequestHeader unset X-Forwarded-For early")


class GrafanaCookieTest(unittest.TestCase):
    def test_session_cookie_is_sent_over_https_only(self):
        # Sessions last ten years, and a cookie without Secure also goes out
        # with any plain http:// request to the name, before a redirect.
        text = (TESLAMATE / "templates" / "grafana.env.j2").read_text()
        self.assertRegex(text, r"(?m)^GF_SECURITY_COOKIE_SECURE=true$")


def flatten_tasks(tasks: list[dict], inherited: dict | None = None) -> list[dict]:
    # Blocks pass their keywords down, so each task carries what it runs with.
    inherited = inherited or {}
    flat = []
    for task in tasks:
        merged = {**inherited, **task}
        if "block" in task:
            keywords = {k: v for k, v in task.items() if k not in ("block", "name")}
            flat.extend(flatten_tasks(task["block"], {**inherited, **keywords}))
        else:
            flat.append(merged)
    return flat


def conditions(task: dict) -> list[str]:
    when = task.get("when", [])
    return [when] if isinstance(when, str) else list(when)


class UdmCloudfrontTest(unittest.TestCase):
    TASKS = UDM / "tasks" / "cloudfront.yml"

    def tasks(self) -> list[dict]:
        return flatten_tasks(load_yaml(self.TASKS))

    def test_udm_cloudfront_tasks_never_touch_ssh_forwards(self):
        # The SSH forwards are how the hosts are reached when the web path
        # breaks, so the component selects the web forwards by port and never
        # names the SSH ports at all.
        for path in (
            self.TASKS,
            UDM / "defaults" / "main.yml",
            UDM / "vars" / "main.yml",
        ):
            text = path.read_text()
            for port in ("11022", "21022"):
                self.assertNotIn(port, text, path)
        text = self.TASKS.read_text()
        for port in ("443", "80"):
            self.assertIn(f"selectattr('dst_port', 'equalto', '{port}')", text)

    def test_component_is_imported_and_off_by_default(self):
        imports = {
            task["ansible.builtin.import_tasks"]: task.get("tags")
            for task in load_yaml(UDM / "tasks" / "main.yml")
        }
        self.assertEqual(imports.get("cloudfront.yml"), ["udm_cloudfront", "update"])
        defaults = load_yaml(UDM / "defaults" / "main.yml")
        self.assertIs(defaults["udm_cloudfront_enforce"], False)

    def test_api_key_is_the_failover_secret_reference(self):
        ours = load_yaml(UDM / "vars" / "main.yml")
        theirs = load_yaml(SECONDARY / "vars" / "main.yml")
        self.assertEqual(
            ours["udm_unifi_api_key"],
            theirs["homeassistant_ha_secondary_unifi_api_key"],
        )
        self.assertEqual(
            ours["udm_unifi_console"],
            theirs["homeassistant_ha_secondary_unifi_console"],
        )

    def test_tasks_run_on_the_controller_without_become(self):
        for task in self.tasks():
            self.assertEqual(task.get("delegate_to"), "localhost", task["name"])
            self.assertIs(task.get("become"), False, task["name"])

    def test_reads_run_in_check_mode_and_writes_do_not(self):
        calls = [task for task in self.tasks() if "ansible.builtin.uri" in task]
        self.assertTrue(calls)
        for task in calls:
            method = task["ansible.builtin.uri"].get("method", "GET")
            if method == "GET":
                self.assertIs(task.get("check_mode"), False, task["name"])
            else:
                self.assertIn("not ansible_check_mode", conditions(task), task["name"])

    def test_only_the_address_group_changes_without_enforce(self):
        reads = ("ansible.builtin.assert", "ansible.builtin.set_fact")
        for task in self.tasks():
            uri = task.get("ansible.builtin.uri")
            if any(name in task for name in reads) or (
                uri is not None and uri.get("method", "GET") == "GET"
            ):
                continue
            if uri is not None and "traffic-matching-lists" in uri["url"]:
                self.assertNotIn("udm_cloudfront_enforce", conditions(task))
            else:
                self.assertIn("udm_cloudfront_enforce", conditions(task), task["name"])

    def test_originals_are_saved_before_anything_is_removed(self):
        names = [task["name"] for task in self.tasks()]
        backup = next(i for i, n in enumerate(names) if "Save" in n)
        for i, task in enumerate(self.tasks()):
            module = task.get("ansible.builtin.uri", {})
            if module.get("method") in ("DELETE", "PUT") and (
                "traffic-matching-lists" not in str(module.get("url", ""))
            ):
                self.assertGreater(i, backup, task["name"])


class UdmCloudfrontWriteTest(unittest.TestCase):
    TASKS = UDM / "tasks" / "cloudfront.yml"

    def tasks(self) -> list[dict]:
        return flatten_tasks(load_yaml(self.TASKS))

    def index(self, predicate) -> int:
        return next(i for i, task in enumerate(self.tasks()) if predicate(task))

    def test_failed_writes_report_status_and_body(self):
        # The request carries the API key, so it stays no_log; a separate
        # check prints only the status and the response body.
        tasks = self.tasks()
        for i, task in enumerate(tasks):
            uri = task.get("ansible.builtin.uri")
            if uri is None or uri.get("method", "GET") == "GET":
                continue
            with self.subTest(task=task["name"]):
                self.assertIs(task.get("no_log"), True)
                self.assertEqual(str(task.get("failed_when")), "False")
                self.assertIs(uri.get("return_content"), True)
                register = task["register"]
                check = next(
                    later
                    for later in tasks[i + 1 :]
                    if "ansible.builtin.assert" in later
                    and register in str(later["ansible.builtin.assert"]["that"])
                )
                message = check["ansible.builtin.assert"]["fail_msg"]
                self.assertIn("status", message)
                self.assertIn("json", message)
                self.assertNotIn("loop", check)
                self.assertNotIn("headers", message)
                self.assertNotIn("invocation", message)

    def test_https_limit_is_read_back(self):
        put = self.index(
            lambda t: (
                t.get("ansible.builtin.uri", {}).get("method") == "PUT"
                and "portforward" in t["ansible.builtin.uri"]["url"]
            )
        )
        tasks = self.tasks()
        reread = next(
            i
            for i, t in enumerate(tasks)
            if i > put
            and "ansible.builtin.uri" in t
            and t["ansible.builtin.uri"].get("method", "GET") == "GET"
            and "portforward" in t["ansible.builtin.uri"]["url"]
        )
        check = next(
            t
            for t in tasks[reread + 1 :]
            if "ansible.builtin.assert" in t and tasks[reread]["register"] in str(t)
        )
        that = str(check["ansible.builtin.assert"]["that"])
        for field in (
            "src_firewall_group_id",
            "src_limiting_enabled",
            "src_limiting_type",
        ):
            self.assertIn(field, that)

    def test_no_ipv6_web_allow_may_remain(self):
        tasks = self.tasks()
        text = self.TASKS.read_text()
        self.assertIn("udm_web_allows", text)
        self.assertIn("udm_web_only", text)
        deletes = [
            i
            for i, t in enumerate(tasks)
            if t.get("ansible.builtin.uri", {}).get("method") == "DELETE"
        ]
        # Before any change: every web allow can be removed without closing
        # another port.
        precheck = self.index(
            lambda t: (
                "__udm_cloudfront_ipv6_web"
                in str(t.get("ansible.builtin.assert", {}).get("that", ""))
            )
        )
        first_write = min(
            i
            for i, t in enumerate(tasks)
            if t.get("ansible.builtin.uri", {}).get("method") in ("DELETE", "PUT")
            and "traffic-matching-lists" not in t["ansible.builtin.uri"]["url"]
        )
        self.assertLess(precheck, first_write)
        # After the deletes: the policies are read again and none remains.
        reread = next(
            i
            for i, t in enumerate(tasks)
            if i > max(deletes)
            and "ansible.builtin.uri" in t
            and t["ansible.builtin.uri"].get("method", "GET") == "GET"
            and "firewall/policies" in t["ansible.builtin.uri"]["url"]
        )
        self.assertTrue(
            any(
                "ansible.builtin.assert" in t and "udm_web_allows" in str(t)
                for t in tasks[reread + 1 :]
            )
        )

    def test_originals_are_kept_in_the_state_directory(self):
        self.assertNotIn("tempfile", self.TASKS.read_text())
        self.assertNotIn("/tmp", self.TASKS.read_text())
        variables = load_yaml(UDM / "vars" / "main.yml")
        self.assertRegex(
            variables["udm_cloudfront_backup_dir"], r"XDG_STATE_HOME.*/udm-cloudfront"
        )
        tasks = self.tasks()
        directory = next(
            t["ansible.builtin.file"]
            for t in tasks
            if t.get("ansible.builtin.file", {}).get("path")
            == "{{ udm_cloudfront_backup_dir }}"
        )
        self.assertEqual(directory["state"], "directory")
        self.assertEqual(directory["mode"], "0700")
        saved = next(
            t["ansible.builtin.copy"] for t in tasks if "ansible.builtin.copy" in t
        )
        self.assertTrue(saved["dest"].startswith("{{ udm_cloudfront_backup_dir }}/"))
        self.assertEqual(saved["mode"], "0600")
        agents = (REPO_ROOT / "AGENTS.md").read_text()
        self.assertIn("~/.local/state/udm-cloudfront/", agents)


def load_udm_firewall():
    path = UDM / "filter_plugins" / "udm_firewall.py"
    spec = importlib.util.spec_from_file_location("udm_firewall", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class UdmFirewallFilterTest(unittest.TestCase):
    EXTERNAL = "external-zone"
    LISTS: ClassVar[list[dict]] = [
        {
            "id": "https",
            "type": "PORTS",
            "items": [{"type": "PORT_NUMBER", "value": 443}],
        },
        {
            "id": "http",
            "type": "PORTS",
            "items": [{"type": "PORT_NUMBER", "value": 80}],
        },
        {
            "id": "ssh",
            "type": "PORTS",
            "items": [{"type": "PORT_NUMBER", "value": 11022}],
        },
    ]

    def setUp(self):
        self.module = load_udm_firewall()

    @classmethod
    def policy(cls, name: str, ports=None, **overrides) -> dict:
        policy = {
            "name": name,
            "enabled": True,
            "action": {"type": "ALLOW"},
            "source": {"zoneId": cls.EXTERNAL},
            "destination": {"zoneId": "internal-zone"},
            "ipProtocolScope": {
                "ipVersion": "IPV6",
                "protocolFilter": {
                    "type": "NAMED_PROTOCOL",
                    "protocol": {"name": "TCP"},
                    "matchOpposite": False,
                },
            },
            "metadata": {"origin": "USER_DEFINED"},
        }
        if isinstance(ports, str):
            policy["destination"]["trafficFilter"] = {
                "type": "IP_ADDRESS",
                "portFilter": {
                    "type": "TRAFFIC_MATCHING_LIST",
                    "matchOpposite": False,
                    "trafficMatchingListId": ports,
                },
            }
        elif ports is not None:
            policy["destination"]["trafficFilter"] = {
                "type": "PORT",
                "portFilter": {"type": "PORTS", "matchOpposite": False, "items": ports},
            }
        for key, value in overrides.items():
            policy[key] = value
        return policy

    @staticmethod
    def port(value: int) -> dict:
        return {"type": "PORT_NUMBER", "value": value}

    def names(self, policies: list[dict]) -> list[str]:
        return [policy["name"] for policy in policies]

    def test_selects_every_ipv6_capable_allow_that_reaches_a_web_port(self):
        tcp_udp = {
            "ipVersion": "IPV6",
            "protocolFilter": {"type": "PRESET", "preset": {"name": "TCP_UDP"}},
        }
        policies = [
            self.policy("https list", "https"),
            self.policy("http inline", [self.port(80)]),
            self.policy(
                "dual stack web",
                [self.port(80), self.port(443)],
                ipProtocolScope={"ipVersion": "IPV4_AND_IPV6"},
            ),
            self.policy("web and ssh", [self.port(443), self.port(11022)]),
            self.policy(
                "low range", [{"type": "PORT_NUMBER_RANGE", "start": 1, "stop": 1024}]
            ),
            self.policy(
                "all but ssh",
                None,
                destination={
                    "zoneId": "internal-zone",
                    "trafficFilter": {
                        "portFilter": {
                            "type": "PORTS",
                            "matchOpposite": True,
                            "items": [self.port(22)],
                        }
                    },
                },
            ),
            self.policy("tcp and udp", [self.port(443)], ipProtocolScope=tcp_udp),
            self.policy(
                "any protocol", [self.port(443)], ipProtocolScope={"ipVersion": "IPV6"}
            ),
            self.policy("unknown list", "missing"),
            self.policy("every port", None, ipProtocolScope={"ipVersion": "IPV6"}),
            # None of these reaches a web port over IPv6 with new TCP connections.
            self.policy("ssh", "ssh"),
            self.policy("ipv4 only", "https", ipProtocolScope={"ipVersion": "IPV4"}),
            self.policy("disabled", "https", enabled=False),
            self.policy("from internal", "https", source={"zoneId": "internal-zone"}),
            self.policy("block", "https", action={"type": "BLOCK"}),
            self.policy(
                "icmpv6",
                None,
                ipProtocolScope={
                    "ipVersion": "IPV6",
                    "protocolFilter": {
                        "type": "NAMED_PROTOCOL",
                        "protocol": {"name": "ICMPV6"},
                        "matchOpposite": False,
                    },
                },
            ),
            self.policy(
                "udp",
                [self.port(443)],
                ipProtocolScope={
                    "ipVersion": "IPV6",
                    "protocolFilter": {
                        "type": "NAMED_PROTOCOL",
                        "protocol": {"name": "UDP"},
                        "matchOpposite": False,
                    },
                },
            ),
            self.policy(
                "return traffic",
                None,
                ipProtocolScope={"ipVersion": "IPV4_AND_IPV6"},
                connectionStateFilter=["RELATED", "ESTABLISHED"],
                metadata={"origin": "SYSTEM_DEFINED"},
            ),
        ]

        web = self.module.udm_web_allows(policies, self.LISTS, self.EXTERNAL)

        self.assertEqual(
            self.names(web),
            [
                "https list",
                "http inline",
                "dual stack web",
                "web and ssh",
                "low range",
                "all but ssh",
                "tcp and udp",
                "any protocol",
                "unknown list",
                "every port",
            ],
        )
        self.assertEqual(
            self.names(self.module.udm_web_only(web, self.LISTS)),
            [
                "https list",
                "http inline",
                "dual stack web",
                "tcp and udp",
                "any protocol",
            ],
        )

    def test_web_only_leaves_other_origins(self):
        derived = self.policy("derived", "https", metadata={"origin": "DERIVED"})

        self.assertEqual(self.module.udm_web_only([derived], self.LISTS), [])


class InternetTlsVerificationTest(unittest.TestCase):
    # Both legs cross the internet carrying credentials, so an unverified peer
    # lets an on-path attacker collect them.
    CA_BUNDLE = "/etc/ssl/certs/ca-certificates.crt"

    def test_postfix_verifies_the_relay(self):
        lines = {
            task["ansible.builtin.lineinfile"]["line"]
            for task in load_yaml(POSTFIX_CLIENT / "tasks" / "main_cf.yml")
        }
        self.assertIn("smtp_tls_security_level = secure", lines)
        # Read before the smtp client enters its chroot, unlike smtp_tls_CApath.
        self.assertIn(f"smtp_tls_CAfile = {self.CA_BUNDLE}", lines)

    def test_autodiscover_proxy_verifies_workmail(self):
        text = (AUTODISCOVER / "files" / "autodiscover.conf").read_text()
        self.assertRegex(text, r"(?m)^SSLProxyVerify require$")
        # The default depth of 1 rejects WorkMail's leaf + intermediate chain.
        self.assertRegex(text, r"(?m)^SSLProxyVerifyDepth [3-9]$")
        self.assertRegex(text, rf"(?m)^SSLProxyCACertificateFile {self.CA_BUNDLE}$")
        self.assertNotRegex(text, r"(?m)^SSLProxyCheckPeer\w+ off$")


class SecurityAgentPentestTest(unittest.TestCase):
    # AWS Security Agent pentests send a secret header so that fail2ban, which
    # would otherwise ban them from every service on the host within seconds,
    # ignores their address. Apache records which addresses sent it.
    LOG_LINE = (
        "CustomLog ${APACHE_LOG_DIR}/security_agent_pentest.log "
        '"%{sec}t %a" env=security_agent_pentest'
    )
    SCRIPT = HTTPD / "files" / "fail2ban-ignore-security-agent"

    def ignored(self, log: str | None, ip: str) -> bool:
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "pentest.log"
            if log is not None:
                path.write_text(log)
            result = subprocess.run(
                ["sh", str(self.SCRIPT), ip, str(path)], check=False
            )
        return result.returncode == 0

    def test_apache_marks_and_strips_the_header(self):
        text = (HTTPD / "templates" / "security-agent-pentest.conf.j2").read_text()
        self.assertRegex(
            text,
            r'(?m)^SetEnvIf X-Security-Agent-Pentest "\^\{\{ '
            r'httpd_security_agent_pentest_token \}\}\$" security_agent_pentest$',
        )
        # Not "early": that runs before SetEnvIf reads the header.
        self.assertRegex(text, r"(?m)^RequestHeader unset X-Security-Agent-Pentest$")
        self.assertIn(self.LOG_LINE, text.splitlines())

    def test_vhosts_with_their_own_logs_also_record_the_header(self):
        # A CustomLog in a vhost stops it inheriting the server's.
        for path in ROLES.glob("*/templates/*.rewse.jp.conf.j2"):
            text = path.read_text()
            if "CustomLog" in text:
                lines = [line.strip() for line in text.splitlines()]
                self.assertIn(self.LOG_LINE, lines, path)

    def test_token_is_a_secret_reference(self):
        variables = load_yaml(HTTPD / "vars" / "main.yml")
        self.assertRegex(
            variables["httpd_security_agent_pentest_token"],
            r"^\{\{ lookup\('pipe', 'op read op://ansible/\w+/password'\) \}\}$",
        )

    def test_every_jail_but_sshd_asks_the_script(self):
        text = (HTTPD / "templates" / "fail2ban-security-agent.conf.j2").read_text()
        self.assertRegex(
            text,
            r"(?m)^ignorecommand = /usr/local/sbin/fail2ban-ignore-security-agent "
            r"<ip> /var/log/apache2/security_agent_pentest\.log$",
        )
        self.assertEqual(
            jail(FAIL2BAN / "templates" / "sshd.conf.j2", "sshd")["ignorecommand"], ""
        )

    def test_script_ignores_an_address_seen_recently(self):
        now = int(time.time())
        self.assertTrue(self.ignored(f"{now - 60} 192.0.2.1\n", "192.0.2.1"))

    def test_script_bans_an_address_seen_long_ago(self):
        now = int(time.time())
        self.assertFalse(self.ignored(f"{now - 3 * 3600} 192.0.2.1\n", "192.0.2.1"))

    def test_script_bans_other_addresses(self):
        now = int(time.time())
        self.assertFalse(self.ignored(f"{now} 192.0.2.10\n", "192.0.2.1"))

    def test_script_bans_when_the_log_is_missing(self):
        self.assertFalse(self.ignored(None, "192.0.2.1"))


if __name__ == "__main__":
    unittest.main()
