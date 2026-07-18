from datetime import datetime
from pathlib import Path
import tempfile
import unittest

from src.database.db import Database
from src.demo_data import DEMO_APPS, seed_demo_database


class DemoDataTests(unittest.TestCase):
    def test_demo_seed_is_synthetic_and_repeatable(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "demo.db")
            database.initialize()
            day = datetime(2026, 7, 18, 12, 0, 0)

            seed_demo_database(database, day, configure_preferences=False)
            seed_demo_database(database, day, configure_preferences=False)

            usage = database.get_app_usage_by_date("2026-07-18")
            notes = database.get_manual_notes_by_date("2026-07-18")
            self.assertEqual(len(usage), len(DEMO_APPS))
            self.assertEqual(len(notes), 2)
            self.assertTrue(all("example" not in item.window_title.lower() for item in usage))
            database.close()


if __name__ == "__main__":
    unittest.main()
