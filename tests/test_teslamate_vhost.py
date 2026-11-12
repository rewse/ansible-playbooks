#!/usr/bin/env python3
"""Regression tests for the access rules of the TeslaMate virtual host."""

import pathlib
import re
import unittest

TESLAMATE = pathlib.Path(__file__).resolve().parents[1] / "roles" / "teslamate"
VHOST = TESLAMATE / "templates" / "teslamate.rewse.jp.conf.j2"


def vhost() -> str:
    return VHOST.read_text()


def section(text: str, opening: str, closing: str) -> str:
    match = re.search(
        rf"(?ms)^\s*{re.escape(opening)}\s*$(.*?)^\s*{re.escape(closing)}\s*$", text
    )
    if match is None:
        raise AssertionError(f"{opening} not found")
    return match.group(1)


class TeslamateVhostAuthTest(unittest.TestCase):
    def test_auth_covers_every_path(self):
        root = section(vhost(), '<Location "/">', "</Location>")
        self.assertRegex(root, r"(?m)^\s*AuthType Basic\s*$")
        self.assertRegex(root, r"(?m)^\s*Require valid-user\s*$")

    def test_auth_is_not_tied_to_one_backend_scheme(self):
        # A <Proxy> section matches only the backend URL it names, which leaves
        # the ws:// worker for the LiveView socket outside it.
        self.assertNotIn("<Proxy", vhost())

    def test_only_the_exact_socket_path_skips_auth(self):
        root = section(vhost(), '<Location "/">', "</Location>")
        any_of = section(root, "<RequireAny>", "</RequireAny>")
        exemptions = re.findall(r"(?m)^\s*Require expr (.+?)\s*$", any_of)
        self.assertEqual(exemptions, ["\"%{REQUEST_URI} == '/live/websocket'\""])
        self.assertNotIn("=~", vhost())

    def test_websocket_is_proxied_only_at_the_socket_path(self):
        self.assertEqual(
            re.findall(r"(?m)^\s*ProxyPass\s+(\S+)\s+ws://", vhost()),
            ["/live/websocket"],
        )


class TeslamateVhostCrossSiteTest(unittest.TestCase):
    def test_rejects_cross_site_writes(self):
        text = vhost()
        self.assertRegex(text, r"(?m)^\s*RewriteEngine on\s*$")
        rule = re.search(
            r"(?m)^\s*RewriteCond %\{REQUEST_METHOD\} !\^\(GET\|HEAD\|OPTIONS\)\$\s*\n"
            r"\s*RewriteCond %\{HTTP:Sec-Fetch-Site\} \^\(cross-site\|same-site\)\$"
            r"\s*\n\s*RewriteRule \^ - \[F\]\s*$",
            text,
        )
        self.assertIsNotNone(rule)

    def test_modules_are_enabled(self):
        tasks = (TESLAMATE / "tasks" / "apache.yml").read_text()
        for module in ("auth_basic", "headers", "rewrite"):
            self.assertRegex(tasks, rf"(?m)^\s*- {module}\s*$")


class TeslamateVhostHeadersTest(unittest.TestCase):
    def test_sets_browser_headers_on_every_response(self):
        headers = dict(
            re.findall(r'(?m)^\s*Header always set (\S+) "([^"]*)"\s*$', vhost())
        )
        self.assertEqual(
            headers,
            {
                "Strict-Transport-Security": "max-age=31536000",
                "X-Content-Type-Options": "nosniff",
                "X-Frame-Options": "SAMEORIGIN",
            },
        )


if __name__ == "__main__":
    unittest.main()
