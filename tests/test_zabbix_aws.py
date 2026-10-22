#!/usr/bin/env python3
"""Regression tests for the zabbix_aws CloudFront and WAF collector."""

import pathlib
import unittest

FILES = pathlib.Path(__file__).resolve().parents[1] / "roles" / "zabbix_aws" / "files"


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
