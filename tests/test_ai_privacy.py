import unittest

from src.database.models import AppUsage, ManualNote
from src.summary.ai_summary_generator import (
    build_preview,
    build_sanitized_payload,
    redact_sensitive_text,
)


class AiPrivacyTests(unittest.TestCase):
    def setUp(self):
        self.usage = [
            AppUsage(
                1,
                "2026-07-18",
                "Code",
                "Private Plan - alice@example.com - C:\\Users\\Alice\\secret.txt",
                "2026-07-18 10:00:00",
                "2026-07-18 10:30:00",
                1800,
                "2026-07-18 10:00:00",
            )
        ]
        self.notes = [
            ManualNote(
                1,
                "2026-07-18",
                "Review C:\\Users\\Alice\\plan.txt with alice@example.com at https://example.com/private",
                "2026-07-18 10:15:00",
            )
        ]

    def test_redacts_common_sensitive_values(self):
        redacted = redact_sensitive_text(self.notes[0].content)
        self.assertNotIn("alice@example.com", redacted)
        self.assertNotIn("C:\\Users\\Alice", redacted)
        self.assertNotIn("https://example.com", redacted)

    def test_window_titles_are_never_in_ai_payload(self):
        payload = build_sanitized_payload(
            "2026-07-18",
            self.usage,
            self.notes,
            include_notes=False,
        )
        preview = build_preview(payload, "en")
        self.assertIn("Code", preview)
        self.assertNotIn("Private Plan", preview)
        self.assertNotIn("alice@example.com", preview)
        self.assertEqual(payload.notes, ())

    def test_notes_require_opt_in_and_are_redacted(self):
        payload = build_sanitized_payload(
            "2026-07-18",
            self.usage,
            self.notes,
            include_notes=True,
        )
        self.assertEqual(len(payload.notes), 1)
        self.assertNotIn("alice@example.com", payload.notes[0])
        self.assertNotIn("C:\\Users\\Alice", payload.notes[0])


if __name__ == "__main__":
    unittest.main()
