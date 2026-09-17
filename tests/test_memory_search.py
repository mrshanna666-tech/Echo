from pathlib import Path
import sqlite3
import tempfile
import unittest

from src.database.db import Database
from src.ui.pages.ask_echo_page import answer_from_evidence


class MemorySearchTests(unittest.TestCase):
    def test_existing_database_is_indexed_during_upgrade(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "activity.db"
            connection = sqlite3.connect(path)
            connection.executescript(
                """
                CREATE TABLE app_usage (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT NOT NULL,
                    app_name TEXT NOT NULL, window_title TEXT, start_time TEXT NOT NULL,
                    end_time TEXT, duration_seconds INTEGER DEFAULT 0, created_at TEXT NOT NULL
                );
                CREATE TABLE manual_notes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT NOT NULL,
                    content TEXT NOT NULL, created_at TEXT NOT NULL
                );
                INSERT INTO manual_notes(date, content, created_at)
                VALUES ('2026-07-29', 'Legacy Echo note', '2026-07-29 08:00:00');
                """
            )
            connection.commit()
            connection.close()

            db = Database(path)
            db.initialize()

            self.assertEqual(db.search_memory("Legacy Echo")[0].detail, "Legacy Echo note")
            self.assertEqual(db._conn.execute("PRAGMA user_version").fetchone()[0], 2)
            db.close()

    def test_full_text_search_returns_multiple_source_types(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Database(Path(directory) / "activity.db")
            db.initialize()
            db.create_app_usage(
                date="2026-07-31",
                app_name="VS Code",
                window_title="Echo memory search",
                start_time="2026-07-31 10:00:00",
                created_at="2026-07-31 10:00:00",
            )
            db.add_manual_note(
                date="2026-07-31",
                content="Finish the Echo search evidence flow",
                created_at="2026-07-31 10:30:00",
            )

            evidence = db.search_memory("Echo", limit=10)

            self.assertEqual({item.kind for item in evidence}, {"activity", "note"})
            answer = answer_from_evidence("Echo", evidence)
            self.assertTrue(answer.found)
            self.assertEqual(len(answer.records), 2)
            db.close()

    def test_confirmed_memory_is_searchable_exportable_and_reversible(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Database(Path(directory) / "activity.db")
            db.initialize()
            memory_id = db.create_confirmed_memory(
                query="What was I working on?",
                content="This activity belongs to Project Echo.",
                created_at="2026-07-31 11:00:00",
            )

            self.assertIsNotNone(memory_id)
            self.assertEqual(db.search_memory("Project Echo")[0].kind, "confirmed")
            self.assertEqual(len(db.export_records()["confirmed_memories"]), 1)
            self.assertTrue(db.delete_confirmed_memory(memory_id))
            self.assertEqual(db.search_memory("Project Echo"), [])
            db.close()

    def test_date_filter_keeps_evidence_scoped(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Database(Path(directory) / "activity.db")
            db.initialize()
            for date in ("2026-07-30", "2026-07-31"):
                db.add_manual_note(
                    date=date,
                    content="Echo planning",
                    created_at=f"{date} 09:00:00",
                )

            evidence = db.search_memory("Echo", date="2026-07-31")

            self.assertEqual([item.date for item in evidence], ["2026-07-31"])
            db.close()


if __name__ == "__main__":
    unittest.main()
