#!/usr/bin/env python3
"""Regression tests for the CloudFront origin configuration."""

import pathlib
import re
import unittest

import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
SITE = REPO_ROOT / "inventory" / "group_vars" / "all" / "site.yml"

OFFICE_EXPRESSION = re.compile(
    r"""^\{\{ lookup\('pipe', 'op read "op://ansible/[0-9a-z]{26}/ipv4"'\) """
    r"""\| split\(','\) \}\}$"""
)


class SiteTest(unittest.TestCase):
    def test_site_holds_no_office_cidr_literals(self):
        text = SITE.read_text()
        for literal in ("13.113.", "15.248.", "w.amazon.com"):
            self.assertNotIn(literal, text)
        value = yaml.safe_load(text)["networks"]["office_public_ipv4"]
        self.assertIsInstance(value, str)
        self.assertRegex(value, OFFICE_EXPRESSION)


if __name__ == "__main__":
    unittest.main()
