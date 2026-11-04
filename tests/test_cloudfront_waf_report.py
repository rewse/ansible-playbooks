#!/usr/bin/env python3
"""Unit tests for the cloudfront-waf-report script."""

import importlib.machinery
import ipaddress
import pathlib
import types
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "roles" / "cloudfront_waf_report" / "files" / "cloudfront-waf-report"
JST = ZoneInfo("Asia/Tokyo")


def load_script() -> types.ModuleType:
    loader = importlib.machinery.SourceFileLoader("cloudfront_waf_report", str(SCRIPT))
    module = types.ModuleType(loader.name)
    module.__file__ = str(SCRIPT)
    loader.exec_module(module)
    return module


report = load_script()


class PeriodTest(unittest.TestCase):
    def test_saturday_morning_covers_previous_saturday_to_friday(self):
        now = datetime(2026, 11, 7, 7, 47, tzinfo=JST)
        self.assertEqual(
            report.report_period(now),
            (datetime(2026, 10, 31, tzinfo=JST), datetime(2026, 11, 7, tzinfo=JST)),
        )

    def test_midweek_run_uses_last_completed_week(self):
        now = datetime(2026, 11, 4, 12, 0, tzinfo=JST)
        self.assertEqual(report.report_period(now)[1], datetime(2026, 10, 31, tzinfo=JST))

    def test_period_is_computed_in_jst_for_utc_input(self):
        # 2026-11-06T16:00Z is Saturday 01:00 in Japan.
        now = datetime(2026, 11, 6, 16, 0, tzinfo=ZoneInfo("UTC"))
        self.assertEqual(report.report_period(now)[1], datetime(2026, 11, 7, tzinfo=JST))


class QueryTest(unittest.TestCase):
    def test_origin_filter_includes_japan_and_each_office_cidr(self):
        text = report.origin_filter(["192.0.2.0/24", "198.51.100.0/24"])
        self.assertIn('httpRequest.country = "JP"', text)
        self.assertIn('isIpv4InSubnet(httpRequest.clientIp, "192.0.2.0/24")', text)
        self.assertIn('isIpv4InSubnet(httpRequest.clientIp, "198.51.100.0/24")', text)

    def test_origin_filter_without_office_is_japan_only(self):
        self.assertEqual(report.origin_filter([]), '(httpRequest.country = "JP")')

    def test_candidate_queries_have_the_four_keys(self):
        self.assertEqual(
            sorted(report.candidate_queries([])),
            ["allowed_scans", "blocked_from_self", "blocked_on_services", "rate_limited_self"],
        )

    def test_allowed_scans_excludes_pentest_and_self(self):
        q = report.candidate_queries(["192.0.2.0/24"])["allowed_scans"]
        self.assertIn('terminatingRuleId != "AllowSecurityAgentPentest"', q)
        self.assertIn("not (", q)

    def test_every_candidate_query_is_bounded(self):
        for name, q in report.candidate_queries([]).items():
            with self.subTest(name=name):
                self.assertTrue(q.rstrip().endswith("| limit 50"))

    def test_label_origin_prefers_office(self):
        nets = [ipaddress.ip_network("192.0.2.0/24")]
        self.assertEqual(report.label_origin("JP", "192.0.2.5", nets), "office")
        self.assertEqual(report.label_origin("JP", "203.0.113.1", nets), "japan")
        self.assertEqual(report.label_origin("BG", "203.0.113.1", nets), "other")

    def test_label_origin_tolerates_bad_address(self):
        nets = [ipaddress.ip_network("192.0.2.0/24")]
        self.assertEqual(report.label_origin("BG", "not-an-ip", nets), "other")


class SanitizeTest(unittest.TestCase):
    def test_sanitize_strips_control_characters(self):
        self.assertEqual(report.sanitize("a\nb\x1b[0mc\td"), "a b [0mc d")

    def test_sanitize_truncates_long_values(self):
        self.assertEqual(len(report.sanitize("x" * 500)), 200)


class FollowupTest(unittest.TestCase):
    NOW = datetime(2026, 11, 7, 7, 47, tzinfo=JST)

    def spec(self, **kw):
        base = {
            "purpose": "p",
            "query": 'filter action = "BLOCK"',
            "start": "2026-10-31T00:00:00+09:00",
            "end": "2026-11-07T00:00:00+09:00",
        }
        return base | kw

    def test_followup_appends_limit(self):
        query, start, end = report.validate_followup(self.spec(), self.NOW)
        self.assertTrue(query.endswith("| limit 100"))
        self.assertEqual(start, datetime(2026, 10, 31, tzinfo=JST))
        self.assertEqual(end, datetime(2026, 11, 7, tzinfo=JST))

    def test_followup_keeps_existing_limit(self):
        query, _, _ = report.validate_followup(self.spec(query="fields @message | limit 5"), self.NOW)
        self.assertEqual(query, "fields @message | limit 5")

    def test_followup_rejects_source_and_log_group(self):
        for q in ["SOURCE logGroups(namePrefix: ['x']) | fields @message", "fields logGroup"]:
            with self.subTest(q=q), self.assertRaises(ValueError):
                report.validate_followup(self.spec(query=q), self.NOW)

    def test_followup_rejects_period_outside_retention(self):
        with self.assertRaises(ValueError):
            report.validate_followup(self.spec(start="2026-07-01T00:00:00+09:00"), self.NOW)

    def test_followup_rejects_future_end(self):
        with self.assertRaises(ValueError):
            report.validate_followup(self.spec(end="2026-11-08T00:00:00+09:00"), self.NOW)

    def test_followup_rejects_malformed_spec(self):
        for spec in [{}, self.spec(query=5), self.spec(start="yesterday"), self.spec(query="x" * 2001)]:
            with self.subTest(spec=str(spec)[:40]), self.assertRaises(ValueError):
                report.validate_followup(spec, self.NOW)


if __name__ == "__main__":
    unittest.main()
