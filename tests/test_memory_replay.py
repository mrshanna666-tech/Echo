from datetime import datetime
import unittest

from src.database.models import AppUsage, ManualNote
from src.ui.pages.memory_page import replay_window


class MemoryReplayTests(unittest.TestCase):
    def test_replay_window_includes_overlapping_usage_and_nearby_note(self):
        usages = [
            AppUsage(1, "2026-07-13", "Code", "Echo", "2026-07-13 14:20:00", "2026-07-13 15:10:00", 3000, "2026-07-13 14:20:00"),
            AppUsage(2, "2026-07-13", "Browser", "Docs", "2026-07-13 16:00:00", "2026-07-13 16:10:00", 600, "2026-07-13 16:00:00"),
        ]
        notes = [ManualNote(1, "2026-07-13", "继续完善", "2026-07-13 15:12:00")]
        selected_usage, selected_notes = replay_window(usages, notes, datetime(2026, 7, 13, 15, 0))
        self.assertEqual([item.app_name for item in selected_usage], ["Code"])
        self.assertEqual([item.content for item in selected_notes], ["继续完善"])

    def test_replay_window_excludes_distant_records(self):
        usages = [AppUsage(1, "2026-07-13", "Code", "Echo", "2026-07-13 10:00:00", "2026-07-13 10:10:00", 600, "2026-07-13 10:00:00")]
        selected_usage, selected_notes = replay_window(usages, [], datetime(2026, 7, 13, 15, 0))
        self.assertEqual(selected_usage, [])
        self.assertEqual(selected_notes, [])


if __name__ == "__main__":
    unittest.main()
