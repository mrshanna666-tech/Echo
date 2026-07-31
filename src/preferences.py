from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path

from src.config import DATA_DIR


logger = logging.getLogger(__name__)
PREFERENCES_PATH = DATA_DIR / "preferences.json"


@dataclass(frozen=True)
class Preferences:
    excluded_keywords: tuple[str, ...] = (
        "1password", "bitwarden", "keepass", "inprivate", "无痕",
    )
    idle_minutes: int = 5
    auto_lock_enabled: bool = True
    auto_lock_minutes: int = 15
    language: str = "zh-CN"
    ai_enabled: bool = False
    ai_include_notes: bool = False
    ai_provider: str = "openai"
    local_ai_base_url: str = "http://127.0.0.1:11434/v1"
    local_ai_model: str = ""


def load_preferences(path: Path = PREFERENCES_PATH) -> Preferences:
    try:
        if not path.exists():
            return Preferences()
        data = json.loads(path.read_text(encoding="utf-8"))
        keywords = tuple(
            str(item).strip().lower()
            for item in data.get("excluded_keywords", [])
            if str(item).strip()
        )
        idle_minutes = max(1, min(int(data.get("idle_minutes", 5)), 120))
        auto_lock_minutes = max(1, min(int(data.get("auto_lock_minutes", 15)), 120))
        language = str(data.get("language", "zh-CN"))
        if language not in {"zh-CN", "en"}:
            language = "zh-CN"
        ai_provider = str(data.get("ai_provider", "openai"))
        if ai_provider not in {"openai", "local"}:
            ai_provider = "openai"
        return Preferences(
            excluded_keywords=keywords or Preferences().excluded_keywords,
            idle_minutes=idle_minutes,
            auto_lock_enabled=bool(data.get("auto_lock_enabled", True)),
            auto_lock_minutes=auto_lock_minutes,
            language=language,
            ai_enabled=bool(data.get("ai_enabled", False)),
            ai_include_notes=bool(data.get("ai_include_notes", False)),
            ai_provider=ai_provider,
            local_ai_base_url=str(data.get("local_ai_base_url", Preferences().local_ai_base_url)).strip() or Preferences().local_ai_base_url,
            local_ai_model=str(data.get("local_ai_model", "")).strip(),
        )
    except Exception:
        logger.exception("Failed to load preferences; defaults will be used.")
        return Preferences()


def save_preferences(preferences: Preferences, path: Path = PREFERENCES_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = asdict(preferences)
    payload["excluded_keywords"] = list(preferences.excluded_keywords)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)
