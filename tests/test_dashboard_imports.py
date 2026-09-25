import importlib
import unittest
from unittest.mock import Mock, patch


class DashboardImportTests(unittest.TestCase):
    def test_dashboard_wsgi_imports_from_project_root(self):
        module = importlib.import_module("dashboard.wsgi")
        self.assertTrue(hasattr(module, "app"))

    def test_hypothetical_route_handles_missing_prediction_metadata(self):
        from dashboard.app import create_app

        session = Mock()
        session.execute.side_effect = [
            Mock(mappings=Mock(return_value=Mock(all=Mock(return_value=[{"driverId": 1, "forename": "Lewis", "surname": "Hamilton"}])))),
            Mock(mappings=Mock(return_value=Mock(all=Mock(return_value=[{"constructorId": 1, "name": "Mercedes"}])))),
            Mock(mappings=Mock(return_value=Mock(all=Mock(return_value=[])))),
            Mock(mappings=Mock(return_value=Mock(all=Mock(return_value=[])))),
            Mock(scalar=Mock(return_value=1.23)),
            Mock(scalar=Mock(return_value=2.34)),
            Mock(scalar=Mock(return_value=3.45)),
        ]

        app = create_app()
        app.config["TESTING"] = True

        with patch("dashboard.predictions.get_session", return_value=session), patch(
            "dashboard.predictions._prediction_metadata", return_value={}
        ):
            with app.test_client() as client:
                resp = client.post(
                    "/predictions/hypothetical",
                    data={"driver_id": 1, "constructor_id": 1, "qualifying_position": 5},
                    follow_redirects=True,
                )

        self.assertEqual(resp.status_code, 200)
        self.assertIn("Prediction data isn’t available", resp.get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
