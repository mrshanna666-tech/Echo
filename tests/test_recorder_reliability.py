from datetime import datetime
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.database.db import Database
from src.recorder.activity_recorder import ActivityRecorder
from src.recorder.window_tracker import WindowInfo


class StaticTracker:
    def __init__(self, info):
        self.info = info

    def get_foreground_window(self):
        return self.info


class RecorderReliabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.temp.name) / "activity.db")
        self.db.initialize()

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def test_activity_is_split_at_midnight(self):
        info = WindowInfo("Editor", "notes", 1)
        recorder = ActivityRecorder(self.db, StaticTracker(info))
        times = [
            datetime(2026, 7, 11, 23, 59, 50),
            datetime(2026, 7, 11, 23, 59, 50),
            datetime(2026, 7, 12, 0, 0, 10),
        ]
        with patch("src.recorder.activity_recorder.now", side_effect=times):
            recorder.tick()
            recorder.tick()
        first = self.db.get_app_usage_by_date("2026-07-11")[0]
        second = self.db.get_app_usage_by_date("2026-07-12")[0]
        self.assertEqual(first.duration_seconds, 10)
        self.assertEqual(first.end_time, "2026-07-12 00:00:00")
        self.assertEqual(second.end_time, "2026-07-12 00:00:10")
        self.assertEqual(second.duration_seconds, 10)
        self.assertIsNotNone(recorder.current)

    def test_recovery_closes_unfinished_record_at_persisted_duration(self):
        record_id = self.db.create_app_usage(
            date="2026-07-11", app_name="Editor", window_title="notes",
            start_time="2026-07-11 10:00:00", created_at="2026-07-11 10:00:00"
        )
        self.db.finish_app_usage(record_id, end_time="2026-07-11 10:05:00", duration_seconds=300)
        self.db._conn.execute("UPDATE app_usage SET end_time = NULL WHERE id = ?", (record_id,))
        self.db._conn.commit()
        self.assertEqual(self.db.recover_unfinished_app_usage(end_time="2026-07-11 11:00:00"), 1)
        row = self.db.get_app_usage_by_date("2026-07-11")[0]
        self.assertEqual(row.end_time, "2026-07-11 10:05:00")

    def test_unchanged_foreground_window_is_checkpointed_each_tick(self):
        info = WindowInfo("Editor", "notes", 1)
        recorder = ActivityRecorder(self.db, StaticTracker(info))
        times = [
            datetime(2026, 7, 11, 10, 0, 0),
            datetime(2026, 7, 11, 10, 0, 0),
            datetime(2026, 7, 11, 10, 0, 3),
        ]
        with patch("src.recorder.activity_recorder.now", side_effect=times):
            recorder.tick()
            recorder.tick()

        row = self.db.get_app_usage_by_date("2026-07-11")[0]
        self.assertEqual(row.end_time, "2026-07-11 10:00:03")
        self.assertEqual(row.duration_seconds, 3)
        self.assertIsNotNone(recorder.current)

    def test_short_activity_is_removed_after_switch(self):
        first = WindowInfo("Popup", "notification", 1)
        second = WindowInfo("Editor", "notes", 2)
        tracker = StaticTracker(first)
        recorder = ActivityRecorder(self.db, tracker)
        times = [
            datetime(2026, 7, 11, 10, 0, 0),
            datetime(2026, 7, 11, 10, 0, 0),
            datetime(2026, 7, 11, 10, 0, 3),
            datetime(2026, 7, 11, 10, 0, 3),
            datetime(2026, 7, 11, 10, 0, 3),
        ]
        with patch("src.recorder.activity_recorder.now", side_effect=times):
            recorder.tick()
            tracker.info = second
            recorder.tick()

        rows = self.db.get_app_usage_by_date("2026-07-11")
        self.assertEqual([row.app_name for row in rows], ["Editor"])
        self.assertEqual(recorder.current.info, second)


if __name__ == "__main__":
    unittest.main()
