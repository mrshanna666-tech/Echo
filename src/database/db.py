from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from src.database.models import AppUsage, ManualNote


logger = logging.getLogger(__name__)


class Database:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None
        self._connect()

    def _connect(self) -> None:
        try:
            self._conn = sqlite3.connect(str(self.db_path))
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL;")
            self._conn.execute("PRAGMA foreign_keys=ON;")
            logger.info("Database connected: %s", self.db_path)
        except sqlite3.Error:
            self._conn = None
            logger.exception("Database connection failed: %s", self.db_path)

    def initialize(self) -> None:
        if self._conn is None:
            logger.error("Database initialization skipped because connection is unavailable.")
            return
        try:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS app_usage (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT NOT NULL,
                    app_name TEXT NOT NULL,
                    window_title TEXT,
                    start_time TEXT NOT NULL,
                    end_time TEXT,
                    duration_seconds INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_app_usage_date_start
                ON app_usage (date, start_time);

                CREATE TABLE IF NOT EXISTS manual_notes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_manual_notes_date_created
                ON manual_notes (date, created_at);
                """
            )
            self._conn.commit()
            logger.info("Database initialized.")
        except sqlite3.Error:
            logger.exception("Database initialization failed.")

    def create_app_usage(
        self,
        *,
        date: str,
        app_name: str,
        window_title: str,
        start_time: str,
        created_at: str,
    ) -> int | None:
        if self._conn is None:
            logger.error("App usage insert skipped because database is unavailable.")
            return None
        try:
            cursor = self._conn.execute(
                """
                INSERT INTO app_usage
                (date, app_name, window_title, start_time, end_time, duration_seconds, created_at)
                VALUES (?, ?, ?, ?, NULL, 0, ?)
                """,
                (date, app_name or "Unknown", window_title or "", start_time, created_at),
            )
            self._conn.commit()
            return int(cursor.lastrowid)
        except sqlite3.Error:
            logger.exception("App usage insert failed.")
            return None

    def finish_app_usage(self, usage_id: int, *, end_time: str, duration_seconds: int) -> bool:
        if self._conn is None:
            logger.error("App usage update skipped because database is unavailable.")
            return False
        try:
            self._conn.execute(
                """
                UPDATE app_usage
                SET end_time = ?, duration_seconds = ?
                WHERE id = ?
                """,
                (end_time, max(duration_seconds, 0), usage_id),
            )
            self._conn.commit()
            return True
        except sqlite3.Error:
            logger.exception("App usage update failed. usage_id=%s", usage_id)
            return False

    def delete_app_usage(self, usage_id: int) -> bool:
        if self._conn is None:
            logger.error("App usage deletion skipped because database is unavailable.")
            return False
        try:
            self._conn.execute("DELETE FROM app_usage WHERE id = ?", (usage_id,))
            self._conn.commit()
            return True
        except sqlite3.Error:
            logger.exception("App usage deletion failed. usage_id=%s", usage_id)
            return False

    def recover_unfinished_app_usage(self, *, end_time: str) -> int:
        """Close records left open by a crash, using their last persisted duration."""
        if self._conn is None:
            logger.error("App usage recovery skipped because database is unavailable.")
            return 0
        try:
            cursor = self._conn.execute(
                """
                UPDATE app_usage
                SET end_time = datetime(start_time, '+' || max(duration_seconds, 0) || ' seconds')
                WHERE end_time IS NULL AND start_time < ?
                """,
                (end_time,),
            )
            self._conn.commit()
            count = max(cursor.rowcount, 0)
            if count:
                logger.warning("Recovered %s unfinished app usage record(s).", count)
            return count
        except sqlite3.Error:
            logger.exception("App usage recovery failed.")
            return 0

    def add_manual_note(self, *, date: str, content: str, created_at: str) -> int | None:
        if self._conn is None:
            logger.error("Manual note insert skipped because database is unavailable.")
            return None
        try:
            cursor = self._conn.execute(
                """
                INSERT INTO manual_notes (date, content, created_at)
                VALUES (?, ?, ?)
                """,
                (date, content, created_at),
            )
            self._conn.commit()
            return int(cursor.lastrowid)
        except sqlite3.Error:
            logger.exception("Manual note insert failed.")
            return None

    def get_app_usage_by_date(self, date: str) -> list[AppUsage]:
        if self._conn is None:
            logger.error("App usage query skipped because database is unavailable.")
            return []
        try:
            rows = self._conn.execute(
                """
                SELECT id, date, app_name, window_title, start_time, end_time,
                       duration_seconds, created_at
                FROM app_usage
                WHERE date = ?
                ORDER BY start_time ASC
                """,
                (date,),
            ).fetchall()
            return [AppUsage(**dict(row)) for row in rows]
        except sqlite3.Error:
            logger.exception("App usage query failed. date=%s", date)
            return []

    def get_manual_notes_by_date(self, date: str) -> list[ManualNote]:
        if self._conn is None:
            logger.error("Manual note query skipped because database is unavailable.")
            return []
        try:
            rows = self._conn.execute(
                """
                SELECT id, date, content, created_at
                FROM manual_notes
                WHERE date = ?
                ORDER BY created_at ASC
                """,
                (date,),
            ).fetchall()
            return [ManualNote(**dict(row)) for row in rows]
        except sqlite3.Error:
            logger.exception("Manual note query failed. date=%s", date)
            return []

    def search_manual_notes(self, query: str, limit: int = 200) -> list[ManualNote]:
        if self._conn is None or not query.strip():
            return []
        try:
            pattern = f"%{query.strip()}%"
            rows = self._conn.execute(
                """SELECT id, date, content, created_at FROM manual_notes
                   WHERE content LIKE ? OR date LIKE ?
                   ORDER BY created_at DESC LIMIT ?""",
                (pattern, pattern, max(1, min(limit, 1000))),
            ).fetchall()
            return [ManualNote(**dict(row)) for row in rows]
        except sqlite3.Error:
            logger.exception("Manual note search failed.")
            return []

    def get_recent_app_usage(self, limit: int = 500) -> list[AppUsage]:
        if self._conn is None:
            return []
        try:
            rows = self._conn.execute(
                """SELECT id, date, app_name, window_title, start_time, end_time,
                          duration_seconds, created_at
                   FROM app_usage ORDER BY start_time DESC LIMIT ?""",
                (max(1, min(limit, 5000)),),
            ).fetchall()
            return [AppUsage(**dict(row)) for row in reversed(rows)]
        except sqlite3.Error:
            logger.exception("Recent app usage query failed.")
            return []

    def count_records_by_date(self, date: str) -> tuple[int, int]:
        """Return (app usage count, manual note count) for a date."""
        if self._conn is None:
            return 0, 0
        try:
            usage = self._conn.execute(
                "SELECT COUNT(*) FROM app_usage WHERE date = ?", (date,)
            ).fetchone()[0]
            notes = self._conn.execute(
                "SELECT COUNT(*) FROM manual_notes WHERE date = ?", (date,)
            ).fetchone()[0]
            return int(usage), int(notes)
        except sqlite3.Error:
            logger.exception("Record count query failed. date=%s", date)
            return 0, 0

    def export_records(self) -> dict[str, list[dict]]:
        """Return all database records as JSON-serializable dictionaries."""
        if self._conn is None:
            return {"app_usage": [], "manual_notes": []}
        try:
            usage = self._conn.execute(
                "SELECT * FROM app_usage ORDER BY start_time"
            ).fetchall()
            notes = self._conn.execute(
                "SELECT * FROM manual_notes ORDER BY created_at"
            ).fetchall()
            return {
                "app_usage": [dict(row) for row in usage],
                "manual_notes": [dict(row) for row in notes],
            }
        except sqlite3.Error:
            logger.exception("Record export query failed.")
            return {"app_usage": [], "manual_notes": []}

    def delete_records_by_date(self, date: str) -> tuple[int, int]:
        """Delete app usage and manual notes for a date, returning deleted counts."""
        if self._conn is None:
            return 0, 0
        try:
            usage = self._conn.execute(
                "DELETE FROM app_usage WHERE date = ?", (date,)
            ).rowcount
            notes = self._conn.execute(
                "DELETE FROM manual_notes WHERE date = ?", (date,)
            ).rowcount
            self._conn.commit()
            return max(usage, 0), max(notes, 0)
        except sqlite3.Error:
            self._conn.rollback()
            logger.exception("Record deletion failed. date=%s", date)
            return 0, 0

    def get_first_record_date(self) -> str | None:
        if self._conn is None:
            logger.error("First record date query skipped because database is unavailable.")
            return None
        try:
            row = self._conn.execute(
                """
                SELECT MIN(date) AS first_date FROM (
                    SELECT date FROM app_usage
                    UNION ALL
                    SELECT date FROM manual_notes
                )
                """
            ).fetchone()
            return row["first_date"] if row and row["first_date"] else None
        except sqlite3.Error:
            logger.exception("First record date query failed.")
            return None

    def close(self) -> None:
        if self._conn is None:
            return
        try:
            self._conn.commit()
            self._conn.close()
            logger.info("Database closed.")
        except sqlite3.Error:
            logger.exception("Database close failed.")

    def backup_to(self, destination: Path) -> None:
        """Create a consistent SQLite backup, including WAL contents."""
        if self._conn is None:
            raise RuntimeError("Database connection is unavailable")
        destination.parent.mkdir(parents=True, exist_ok=True)
        target = sqlite3.connect(str(destination))
        try:
            self._conn.commit()
            self._conn.backup(target)
            target.commit()
        finally:
            target.close()
