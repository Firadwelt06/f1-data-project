import importlib
import unittest


class DashboardImportTests(unittest.TestCase):
    def test_dashboard_wsgi_imports_from_project_root(self):
        module = importlib.import_module("dashboard.wsgi")
        self.assertTrue(hasattr(module, "app"))


if __name__ == "__main__":
    unittest.main()
