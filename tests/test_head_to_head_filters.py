import sys
import unittest
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dashboard"))

from analytics import get_shared_race_driver_candidates


class HeadToHeadFilterTests(unittest.TestCase):
    def test_get_shared_race_driver_candidates_returns_only_overlap_drivers(self):
        session = Mock()
        session.execute.return_value.mappings.return_value.all.return_value = [
            {"driverId": 2, "forename": "Lando", "surname": "Norris"},
            {"driverId": 3, "forename": "Fernando", "surname": "Alonso"},
        ]

        drivers = get_shared_race_driver_candidates(session, 1)

        self.assertEqual([d["driverId"] for d in drivers], [2, 3])


if __name__ == "__main__":
    unittest.main()
