from pathlib import Path
import tempfile
import unittest
import zipfile

from src.data_export import export_all_data
from src.database.db import Database


class DataExportTests(unittest.TestCase):
    def test_export_contains_records_json(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            db = Database(root / "activity.db")
            db.initialize()
            db.add_manual_note(
                date="2026-07-17", content="portable note", created_at="2026-07-17 10:00:00",
            )
            output = export_all_data(db, root / "export.zip")
            self.assertTrue(output.exists())
            with zipfile.ZipFile(output) as archive:
                self.assertIn("records.json", archive.namelist())
                self.assertIn("portable note", archive.read("records.json").decode("utf-8"))
            db.close()

    def test_sqlite_backup_contains_wal_records(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            db = Database(root / "activity.db")
            db.initialize()
            db.add_manual_note(
                date="2026-07-17", content="backup note", created_at="2026-07-17 11:00:00",
            )
            backup = root / "backup.db"
            db.backup_to(backup)
            restored = Database(backup)
            restored.initialize()
            self.assertEqual(restored.get_manual_notes_by_date("2026-07-17")[0].content, "backup note")
            restored.close()
            db.close()


if __name__ == "__main__":
    unittest.main()
