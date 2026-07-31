import unittest

from src.database.models import AppUsage, ManualNote
from src.ui.pages.ask_echo_page import answer_from_local_records


class AskEchoAnswerTests(unittest.TestCase):
    def setUp(self):
        self.usage = [
            AppUsage(1, "2026-07-15", "VS Code", "Echo workspace", "2026-07-15 14:20:00", "2026-07-15 15:10:00", 3000, "2026-07-15 14:20:00"),
        ]
        self.notes = [
            ManualNote(1, "2026-07-15", "Continue polishing Echo", "2026-07-15 15:12:00"),
        ]

    def test_returns_only_directly_matching_evidence(self):
        result = answer_from_local_records("When did I use VS Code?", self.usage, self.notes)
        self.assertTrue(result.found)
        self.assertEqual(len(result.evidence), 1)
        self.assertIn("VS Code", result.evidence[0])

    def test_includes_matching_note(self):
        result = answer_from_local_records("Echo", self.usage, self.notes)
        self.assertTrue(result.found)
        self.assertEqual(len(result.evidence), 2)
        self.assertIn("Continue polishing Echo", result.evidence[1])

    def test_reports_when_no_direct_evidence_exists(self):
        result = answer_from_local_records("unrelated project", self.usage, self.notes)
        self.assertFalse(result.found)
        self.assertEqual(result.evidence, ())


if __name__ == "__main__":
    unittest.main()
