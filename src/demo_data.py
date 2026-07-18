from __future__ import annotations

from datetime import datetime, timedelta

from src.database.db import Database
from src.preferences import Preferences, save_preferences
from src.utils.time_utils import DATE_FORMAT, to_db_datetime


DEMO_APPS = (
    ("Focus Writer", "Drafting a personal essay", 48),
    ("Research Library", "Reading saved articles", 34),
    ("Photo Studio", "Organizing a weekend album", 27),
    ("Music Player", "Afternoon focus playlist", 21),
    ("Family Calendar", "Planning the week", 16),
)


def seed_demo_database(
    database: Database,
    day: datetime | None = None,
    *,
    configure_preferences: bool = True,
) -> str:
    """Create a deterministic, synthetic day without touching real user data."""
    day = day or datetime.now()
    date_text = day.strftime(DATE_FORMAT)
    database.delete_records_by_date(date_text)

    cursor = day.replace(hour=8, minute=40, second=0, microsecond=0)
    for app_name, title, minutes in DEMO_APPS:
        end = cursor + timedelta(minutes=minutes)
        usage_id = database.create_app_usage(
            date=date_text,
            app_name=app_name,
            window_title=title,
            start_time=to_db_datetime(cursor),
            created_at=to_db_datetime(cursor),
        )
        if usage_id is not None:
            database.finish_app_usage(
                usage_id,
                end_time=to_db_datetime(end),
                duration_seconds=minutes * 60,
            )
        cursor = end + timedelta(minutes=12)

    database.add_manual_note(
        date=date_text,
        content="A quiet afternoon made space for the idea I had been postponing.",
        created_at=to_db_datetime(day.replace(hour=15, minute=25, second=0, microsecond=0)),
    )
    database.add_manual_note(
        date=date_text,
        content="Remember to share the weekend plan with the family.",
        created_at=to_db_datetime(day.replace(hour=18, minute=10, second=0, microsecond=0)),
    )
    if configure_preferences:
        save_preferences(
            Preferences(
                language="en",
                ai_enabled=True,
                ai_include_notes=False,
            )
        )
    return date_text
