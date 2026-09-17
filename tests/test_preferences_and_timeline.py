from pathlib import Path
import tempfile
import unittest

from src.database.models import AppUsage
from src.database.db import Database
from src.preferences import Preferences, clear_preferences_cache, load_preferences, save_preferences
from src.ui.pages.timeline_page import activity_category, merge_activity_sessions


def usage(identifier: int, app: str, start: str, end: str, seconds: int) -> AppUsage:
    return AppUsage(identifier, start[:10], app, "title", start, end, seconds, start)


class PreferencesAndTimelineTests(unittest.TestCase):
    def test_preferences_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "preferences.json"
            expected = Preferences(("secret", "无痕"), 12)
            save_preferences(expected, path)
            self.assertEqual(load_preferences(path), expected)

    def test_invalid_idle_timeout_is_clamped(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "preferences.json"
            path.write_text('{"excluded_keywords": ["x"], "idle_minutes": 999}', encoding="utf-8")
            self.assertEqual(load_preferences(path).idle_minutes, 120)

    def test_language_and_ai_preferences_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "preferences.json"
            expected = Preferences(
                excluded_keywords=("secret",),
                idle_minutes=8,
                auto_lock_enabled=False,
                auto_lock_minutes=27,
                language="en",
                ai_enabled=True,
                ai_include_notes=True,
                ai_provider="local",
                local_ai_base_url="http://127.0.0.1:1234/v1",
                local_ai_model="echo-small",
            )
            save_preferences(expected, path)
            self.assertEqual(load_preferences(path), expected)

    def test_adjacent_activity_sessions_are_merged(self):
        rows = [
            usage(1, "Code", "2026-07-13 10:00:00", "2026-07-13 10:05:00", 300),
            usage(2, "Code", "2026-07-13 10:06:00", "2026-07-13 10:10:00", 240),
        ]
        sessions = merge_activity_sessions(rows)
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0].duration_seconds, 540)
        self.assertEqual(sessions[0].category, "work")

    def test_communication_category(self):
        self.assertEqual(activity_category("Weixin", "聊天"), "communication")

    def test_database_search_count_and_delete(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Database(Path(directory) / "activity.db")
            db.initialize()
            db.create_app_usage(
                date="2026-07-17", app_name="Code", window_title="Echo",
                start_time="2026-07-17 10:00:00", created_at="2026-07-17 10:00:00",
            )
            db.add_manual_note(
                date="2026-07-17", content="ship search", created_at="2026-07-17 10:01:00",
            )
            self.assertEqual(len(db.search_manual_notes("search")), 1)
            self.assertEqual(db.count_records_by_date("2026-07-17"), (1, 1))
            self.assertEqual(db.delete_records_by_date("2026-07-17"), (1, 1))
            self.assertEqual(db.count_records_by_date("2026-07-17"), (0, 0))
            db.close()

    def test_preferences_cache_and_invalidation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "preferences.json"
            initial = Preferences(("secret",), 10)
            save_preferences(initial, path)
            first = load_preferences(path)
            self.assertEqual(first, initial)
            second = load_preferences(path)
            self.assertIs(first, second)

            updated = Preferences(("secret", "other"), 20)
            save_preferences(updated, path)
            third = load_preferences(path)
            self.assertEqual(third, updated)
            self.assertIsNot(first, third)


if __name__ == "__main__":
    unittest.main()
