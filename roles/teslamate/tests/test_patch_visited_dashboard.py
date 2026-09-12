import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).parents[1] / "files" / "patch_visited_dashboard.py"


VISITED_QUERY = """SELECT
  date_trunc('minute', timezone('UTC', date), '$__timezone') as time,
  avg(latitude) as latitude,
  avg(longitude) as longitude
FROM
  positions
WHERE
  car_id = $car_id AND $__timeFilter(date) and ideal_battery_range_km is not null
GROUP BY 1
ORDER BY 1
"""

DRIVE_DETAILS_QUERY = """SELECT
  $__time(date),
  latitude,
  longitude
FROM positions
WHERE
  car_id = $car_id AND
  $__timeFilter(date)
ORDER BY
  date ASC
"""

TRIP_QUERY = """with unioned_positions as (
    select p.*
    from positions p
    inner join drives d on p.drive_id = d.id
    where p.car_id = $car_id and $__timeFilter(d.start_date)

    union all

    select *
    from positions p
    where p.car_id = $car_id and drive_id is null and $__timeFilter(date))

SELECT $__timeGroup(date, '5s') AS time,
       avg(latitude) AS latitude,
       avg(longitude) AS longitude
from unioned_positions
GROUP BY 1
ORDER BY 1 ASC
"""


def load_module():
    spec = importlib.util.spec_from_file_location("patch_visited_dashboard", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_dashboard(query=VISITED_QUERY, target_count=1):
    target = {
        "refId": "Positions",
        "rawSql": query,
    }
    return {
        "panels": [
            {
                "type": "geomap",
                "targets": [target.copy() for _ in range(target_count)],
            }
        ]
    }


class PatchVisitedDashboardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_module()

    def test_patch_adds_geofence_filter_to_positions_query(self):
        dashboard = make_dashboard()

        patched = self.module.patch_dashboard(
            dashboard, "Yamate-dori Ave., Shinjuku"
        )
        query = patched["panels"][0]["targets"][0]["rawSql"]

        self.assertIn("FROM\n  positions p", query)
        self.assertIn("AND NOT EXISTS (", query)
        self.assertIn("g.name = 'Yamate-dori Ave., Shinjuku'", query)
        self.assertIn("ll_to_earth(p.latitude, p.longitude)", query)
        self.assertLess(query.index("NOT EXISTS"), query.index("GROUP BY 1"))

    def test_patch_adds_geofence_filter_to_drive_details_query(self):
        dashboard = make_dashboard(DRIVE_DETAILS_QUERY)

        patched = self.module.patch_dashboard(dashboard, "Home")
        query = patched["panels"][0]["targets"][0]["rawSql"]

        self.assertIn("FROM positions p", query)
        self.assertIn("AND NOT EXISTS (", query)
        self.assertLess(query.index("NOT EXISTS"), query.index("ORDER BY"))

    def test_patch_adds_geofence_filter_to_trip_query(self):
        dashboard = make_dashboard(TRIP_QUERY)

        patched = self.module.patch_dashboard(dashboard, "Home")
        query = patched["panels"][0]["targets"][0]["rawSql"]

        self.assertIn("from unioned_positions p", query)
        self.assertIn("WHERE NOT EXISTS (", query)
        self.assertNotIn("from unioned_positions p\n  AND NOT EXISTS", query)
        self.assertIn("ll_to_earth(p.latitude, p.longitude)", query)
        self.assertLess(query.index("NOT EXISTS"), query.index("GROUP BY 1"))

    def test_patch_escapes_sql_string_literals(self):
        dashboard = make_dashboard()

        patched = self.module.patch_dashboard(dashboard, "Driver's Home")
        query = patched["panels"][0]["targets"][0]["rawSql"]

        self.assertIn("g.name = 'Driver''s Home'", query)

    def test_patch_is_idempotent(self):
        dashboard = make_dashboard()

        first = self.module.patch_dashboard(dashboard, "Home")
        second = self.module.patch_dashboard(first, "Home")

        self.assertEqual(first, second)
        query = second["panels"][0]["targets"][0]["rawSql"]
        self.assertEqual(query.count(self.module.FILTER_MARKER), 1)

    def test_patch_rejects_missing_positions_query(self):
        with self.assertRaisesRegex(ValueError, "exactly one"):
            self.module.patch_dashboard({"panels": []}, "Home")

    def test_patch_rejects_multiple_positions_queries(self):
        with self.assertRaisesRegex(ValueError, "exactly one"):
            self.module.patch_dashboard(make_dashboard(target_count=2), "Home")

    def test_write_dashboard_preserves_mtime_when_content_is_unchanged(self):
        dashboard = make_dashboard()
        with tempfile.TemporaryDirectory() as directory:
            output_path = Path(directory) / "visited.json"

            self.assertTrue(self.module.write_dashboard(output_path, dashboard))
            first_mtime = output_path.stat().st_mtime_ns
            self.assertFalse(self.module.write_dashboard(output_path, dashboard))

            self.assertEqual(first_mtime, output_path.stat().st_mtime_ns)
            self.assertEqual(dashboard, json.loads(output_path.read_text()))


if __name__ == "__main__":
    unittest.main()
