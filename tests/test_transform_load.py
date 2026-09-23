import unittest
from datetime import time

from etl.schema import analytics_driver_race
from transform_load import cast_time


class CastTimeTests(unittest.TestCase):
    def test_cast_time_strips_utc_z_suffix(self):
        self.assertEqual(cast_time("04:00:00Z"), time(4, 0, 0))

    def test_cast_time_handles_microseconds(self):
        self.assertEqual(cast_time("13:00:00.123456"), time(13, 0, 0))


class AnalyticsSchemaTests(unittest.TestCase):
    def test_analytics_driver_race_has_prior_win_streak_column(self):
        self.assertIn("priorWinStreak", analytics_driver_race.columns)


if __name__ == "__main__":
    unittest.main()
