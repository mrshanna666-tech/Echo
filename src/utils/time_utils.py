from __future__ import annotations

from datetime import datetime, timedelta

from src.i18n import tr


DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"
DATE_FORMAT = "%Y-%m-%d"
TIME_FORMAT = "%H:%M"


def now() -> datetime:
    return datetime.now()


def today_str() -> str:
    return now().strftime(DATE_FORMAT)


def to_db_datetime(value: datetime) -> str:
    return value.strftime(DATETIME_FORMAT)


def parse_db_datetime(value: str) -> datetime:
    return datetime.strptime(value, DATETIME_FORMAT)


def display_time(value: str | None) -> str:
    if not value:
        return "--:--"
    return parse_db_datetime(value).strftime(TIME_FORMAT)


def duration_seconds(start: datetime, end: datetime) -> int:
    seconds = int((end - start).total_seconds())
    return max(seconds, 0)


def human_duration(seconds: int | None) -> str:
    if not seconds:
        return tr("不到 1 分钟", "under 1 min")
    delta = timedelta(seconds=seconds)
    total_minutes = max(int(delta.total_seconds() // 60), 1)
    hours, minutes = divmod(total_minutes, 60)
    if hours and minutes:
        return tr(f"{hours}小时{minutes}分钟", f"{hours}h {minutes}m")
    if hours:
        return tr(f"{hours}小时", f"{hours}h")
    return tr(f"{minutes}分钟", f"{minutes}m")
