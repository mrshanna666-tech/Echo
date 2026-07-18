from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime

from src.config import MAX_POLL_GAP_SECONDS, MIN_ACTIVITY_SECONDS
from src.database.db import Database
from src.recorder.window_tracker import WindowInfo, WindowTracker
from src.utils.time_utils import DATE_FORMAT, duration_seconds, now, to_db_datetime


logger = logging.getLogger(__name__)
_SECRET_TOKEN = re.compile(
    r"\b(?:sk-[A-Za-z0-9_-]{8,}|github_pat_[A-Za-z0-9_]{8,}|gh[pousr]_[A-Za-z0-9]{8,})\b"
)


def redact_sensitive_window_title(title: str) -> str:
    """Remove recognizable secret tokens before persistent storage."""
    return _SECRET_TOKEN.sub("[secret removed]", title)


@dataclass
class ActiveUsage:
    id: int
    info: WindowInfo
    start_time: datetime


class ActivityRecorder:
    def __init__(self, database: Database, tracker: WindowTracker) -> None:
        self.database = database
        self.tracker = tracker
        self.paused = False
        self.current: ActiveUsage | None = None
        self.last_tick_at: datetime | None = None

    def tick(self) -> None:
        tick_time = now()
        try:
            if self._has_abnormal_poll_gap(tick_time):
                self._handle_abnormal_poll_gap()

            self.last_tick_at = tick_time
            if self.paused:
                return

            if self.current and self.current.start_time.date() != tick_time.date():
                midnight = tick_time.replace(hour=0, minute=0, second=0, microsecond=0)
                previous_info = self.current.info
                if not self._finish_current(end=midnight):
                    return
                self._start_usage(previous_info, start=midnight)

            info = self.tracker.get_foreground_window()
            if info is None:
                self._finish_current()
                return

            if self.current and self.current.info.identity == info.identity:
                self._checkpoint_current(end=tick_time)
                return

            self._finish_current()
            self._start_usage(info)
        except Exception:
            logger.exception("Recorder tick failed; next polling cycle will continue.")

    def pause(self) -> None:
        try:
            if self.paused:
                return
            self._finish_current()
            self.paused = True
            logger.info("Recording paused.")
        except Exception:
            logger.exception("Failed to pause recording.")

    def resume(self) -> None:
        try:
            self.paused = False
            self.last_tick_at = None
            logger.info("Recording resumed.")
            self.tick()
        except Exception:
            logger.exception("Failed to resume recording.")

    def shutdown(self) -> None:
        try:
            self._finish_current()
            logger.info("Recorder shutdown completed.")
        except Exception:
            logger.exception("Recorder shutdown failed.")

    def reset_after_data_clear(self) -> None:
        """End the in-memory session before records are removed externally."""
        try:
            self._finish_current()
        finally:
            self.current = None
            self.last_tick_at = None
            logger.info("Recorder state reset after data clear.")

    def refresh_current_duration(self) -> None:
        try:
            if not self.current:
                return
            self._checkpoint_current(end=now())
        except Exception:
            logger.exception("Failed to refresh current activity duration.")

    def _checkpoint_current(self, *, end: datetime) -> bool:
        """Persist an active record without ending the in-memory session."""
        if not self.current:
            return True
        return self.database.finish_app_usage(
            self.current.id,
            end_time=to_db_datetime(end),
            duration_seconds=duration_seconds(self.current.start_time, end),
        )

    def _start_usage(self, info: WindowInfo, *, start: datetime | None = None) -> None:
        start = start or now()
        usage_id = self.database.create_app_usage(
            date=start.strftime(DATE_FORMAT),
            app_name=info.app_name,
            window_title=redact_sensitive_window_title(info.window_title),
            start_time=to_db_datetime(start),
            created_at=to_db_datetime(start),
        )
        if usage_id is None:
            logger.error("Current usage was not started because database insert failed.")
            self.current = None
            return
        self.current = ActiveUsage(id=usage_id, info=info, start_time=start)
        # Window titles can contain document names, search terms, or secrets.
        logger.info("Started usage: app=%s", info.app_name)

    def _finish_current(self, end: datetime | None = None) -> bool:
        if not self.current:
            return True

        end = end or now()
        elapsed = duration_seconds(self.current.start_time, end)
        if elapsed < MIN_ACTIVITY_SECONDS:
            removed = self.database.delete_app_usage(self.current.id)
            if removed:
                logger.info(
                    "Discarded short activity: app=%s duration=%ss",
                    self.current.info.app_name,
                    elapsed,
                )
                self.current = None
            return removed

        saved = self.database.finish_app_usage(
            self.current.id,
            end_time=to_db_datetime(end),
            duration_seconds=elapsed,
        )
        if saved:
            logger.info("Finished usage: app=%s", self.current.info.app_name)
            self.current = None
        return saved

    def _has_abnormal_poll_gap(self, tick_time: datetime) -> bool:
        if self.last_tick_at is None:
            return False
        gap_seconds = duration_seconds(self.last_tick_at, tick_time)
        return gap_seconds > MAX_POLL_GAP_SECONDS

    def _handle_abnormal_poll_gap(self) -> None:
        logger.warning(
            "Abnormal polling gap detected; current usage will end at previous tick time."
        )
        if self.current and self.last_tick_at:
            self._finish_current(end=self.last_tick_at)
