from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from src.config import DATA_DIR
from src.security import protected_path, read_protected_text, write_protected_text
from src.utils.time_utils import today_str


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MoodEntry:
    date: str
    created_at: str
    image_path: str
    mood: str
    note: str


def get_today_mood_dir() -> Path:
    path = DATA_DIR / "moods" / today_str()
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_today_diary_json_path() -> Path:
    return get_diary_json_path(today_str(), create=True)


def get_diary_json_path(date_text: str, create: bool = False) -> Path:
    year, month, day = date_text.split("-")
    path = DATA_DIR / year / month / day
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return protected_path(path / "daily.json")


def create_mood_image_path() -> Path:
    timestamp = datetime.now().strftime("%H%M%S")
    return get_today_mood_dir() / f"mood_{timestamp}_{uuid4().hex[:8]}.jpg"


def append_mood_entry(image_path: Path, mood: str, note: str) -> MoodEntry:
    entry = MoodEntry(
        date=today_str(),
        created_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        image_path=str(image_path),
        mood=mood,
        note=note.strip(),
    )
    json_path = get_today_diary_json_path()
    payload = _read_diary_json(json_path)
    payload.setdefault("date", entry.date)
    payload.setdefault("entries", [])
    payload["entries"].append(
        {
            "type": "mood",
            "created_at": entry.created_at,
            "image_path": entry.image_path,
            "mood": entry.mood,
            "note": entry.note,
        }
    )
    write_protected_text(
        json_path,
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info("Mood entry saved: %s", image_path)
    return entry


def get_mood_entries_by_date(date_text: str) -> list[MoodEntry]:
    json_path = get_diary_json_path(date_text)
    payload = _read_diary_json(json_path)
    entries = []
    for item in payload.get("entries", []):
        if not isinstance(item, dict) or item.get("type") != "mood":
            continue
        entries.append(
            MoodEntry(
                date=date_text,
                created_at=str(item.get("created_at") or ""),
                image_path=str(item.get("image_path") or ""),
                mood=str(item.get("mood") or "平静"),
                note=str(item.get("note") or ""),
            )
        )
    entries.sort(key=lambda item: item.created_at)
    return entries


def _read_diary_json(path: Path) -> dict:
    if not path.exists():
        return {"date": today_str(), "entries": []}
    try:
        data = json.loads(read_protected_text(path, encoding="utf-8"))
    except json.JSONDecodeError:
        logger.exception("Invalid diary JSON, recreating: %s", path)
        return {"date": today_str(), "entries": []}
    if not isinstance(data, dict):
        return {"date": today_str(), "entries": []}
    if not isinstance(data.get("entries"), list):
        data["entries"] = []
    return data
