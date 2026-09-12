import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = (
    Path(__file__).parents[1] / "files" / "patch_vampire_drain_dashboard.py"
)

SOURCE_DURATION = "EXTRACT(EPOCH FROM age(t.start_date, lag(t.end_date) OVER w))"
SOURCE_AGGREGATE = "sum(age(s.end_date, s.start_date))"
SOURCE_CONTAINMENT = (
    "v.start_date <= s.start_date AND s.end_date <= v.end_date"
)

SOURCE_QUERY = """WITH v AS (
  SELECT EXTRACT(EPOCH FROM age(t.start_date, lag(t.end_date) OVER w)) AS duration
  FROM merge t WINDOW w AS (ORDER BY t.start_date)
)
SELECT * FROM v,
LATERAL (
  SELECT EXTRACT(EPOCH FROM sum(age(s.end_date, s.start_date))) AS sleep
  FROM states s
  WHERE state = 'asleep'
    AND v.start_date <= s.start_date AND s.end_date <= v.end_date
) s_asleep,
LATERAL (
  SELECT EXTRACT(EPOCH FROM sum(age(s.end_date, s.start_date))) AS sleep
  FROM states s
  WHERE state = 'offline'
    AND v.start_date <= s.start_date AND s.end_date <= v.end_date
) s_offline
"""


def load_module():
    spec = importlib.util.spec_from_file_location(
        "patch_vampire_drain_dashboard", SCRIPT_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_dashboard(query=SOURCE_QUERY):
    return {"panels": [{"targets": [{"rawSql": query}]}]}


class PatchVampireDrainDashboardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_module()

    def test_patch_clips_asleep_and_offline_to_parking_interval(self):
        patched = self.module.patch_dashboard(make_dashboard())
        query = patched["panels"][0]["targets"][0]["rawSql"]

        self.assertEqual(
            query.count("LEAST(COALESCE(s.end_date, v.end_date), v.end_date)"),
            2,
        )
        self.assertEqual(query.count("s.start_date < v.end_date"), 2)
        self.assertEqual(
            query.count("COALESCE(s.end_date, v.end_date) > v.start_date"), 2
        )

    def test_patch_replaces_age_duration_with_elapsed_seconds(self):
        patched = self.module.patch_dashboard(make_dashboard())
        query = patched["panels"][0]["targets"][0]["rawSql"]

        self.assertIn("t.start_date - lag(t.end_date) OVER w", query)
        self.assertNotIn("age(t.start_date", query)

    def test_patch_rejects_unexpected_state_aggregate_count(self):
        one_aggregate = SOURCE_QUERY.replace(SOURCE_AGGREGATE, "sum(s.duration)", 1)
        three_aggregates = SOURCE_QUERY + SOURCE_AGGREGATE

        for query in (one_aggregate, three_aggregates):
            with self.subTest(count=query.count(SOURCE_AGGREGATE)):
                with self.assertRaisesRegex(ValueError, "state aggregates"):
                    self.module.patch_dashboard(make_dashboard(query))

    def test_patch_rejects_unexpected_duration_count(self):
        no_duration = SOURCE_QUERY.replace(SOURCE_DURATION, "v.duration")
        two_durations = SOURCE_QUERY + SOURCE_DURATION

        for query in (no_duration, two_durations):
            with self.subTest(count=query.count(SOURCE_DURATION)):
                with self.assertRaisesRegex(ValueError, "duration expressions"):
                    self.module.patch_dashboard(make_dashboard(query))

    def test_patch_is_idempotent(self):
        dashboard = make_dashboard()

        first = self.module.patch_dashboard(dashboard)
        second = self.module.patch_dashboard(first)

        self.assertEqual(first, second)
        self.assertEqual(SOURCE_QUERY, dashboard["panels"][0]["targets"][0]["rawSql"])

    def test_patch_rejects_multiple_vampire_drain_queries(self):
        dashboard = {
            "rows": [make_dashboard(), {"nested": make_dashboard()}],
        }

        with self.assertRaisesRegex(ValueError, "exactly one"):
            self.module.patch_dashboard(dashboard)

    def test_write_dashboard_preserves_mtime_when_content_is_unchanged(self):
        dashboard = self.module.patch_dashboard(make_dashboard())
        with tempfile.TemporaryDirectory() as directory:
            output_path = Path(directory) / "vampire-drain.json"

            self.assertTrue(self.module.write_dashboard(output_path, dashboard))
            first_mtime = output_path.stat().st_mtime_ns
            self.assertFalse(self.module.write_dashboard(output_path, dashboard))

            self.assertEqual(first_mtime, output_path.stat().st_mtime_ns)
            self.assertEqual(dashboard, json.loads(output_path.read_text()))


if __name__ == "__main__":
    unittest.main()
