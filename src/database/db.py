from __future__ import annotations

import logging
import os
import re
from pathlib import Path

try:
    from sqlcipher3 import dbapi2 as sqlite3

    SQLCIPHER_AVAILABLE = True
except ImportError:  # pragma: no cover - production requirements include SQLCipher.
    import sqlite3

    SQLCIPHER_AVAILABLE = False

from src.database.models import AppUsage, ConfirmedMemory, ManualNote, MemoryEvidence


logger = logging.getLogger(__name__)


class DatabaseEncryptionError(RuntimeError):
    pass


def migrate_plaintext_database(database_path: Path, encryption_key: bytes) -> None:
    """Atomically replace a plaintext SQLite database with a SQLCipher database."""
    if not SQLCIPHER_AVAILABLE:
        raise DatabaseEncryptionError("SQLCipher is not installed.")
    database_path = Path(database_path)
    if not database_path.exists():
        return
    temporary = database_path.with_suffix(database_path.suffix + ".encrypted.tmp")
    temporary.unlink(missing_ok=True)
    connection = sqlite3.connect(str(database_path))
    try:
        connection.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()
        user_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        escaped_path = str(temporary).replace("'", "''")
        key_literal = encryption_key.hex()
        connection.execute(
            f"ATTACH DATABASE '{escaped_path}' AS encrypted KEY \"x'{key_literal}'\""
        )
        connection.execute("SELECT sqlcipher_export('encrypted')")
        connection.execute(f"PRAGMA encrypted.user_version = {user_version}")
        connection.execute("DETACH DATABASE encrypted")
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    finally:
        connection.close()

    verification = sqlite3.connect(str(temporary))
    try:
        verification.execute(f"PRAGMA key = \"x'{encryption_key.hex()}'\"")
        verification.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()
        cipher_version = verification.execute("PRAGMA cipher_version").fetchone()
        if not cipher_version or not cipher_version[0]:
            raise DatabaseEncryptionError("SQLCipher did not report an active cipher.")
    finally:
        verification.close()
    os.replace(temporary, database_path)


class Database:
    def __init__(self, db_path: Path, encryption_key: bytes | None = None) -> None:
        self.db_path = db_path
        self._encryption_key = bytes(encryption_key) if encryption_key else None
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None
        self._connect()

    def _connect(self) -> None:
        try:
            self._conn = sqlite3.connect(str(self.db_path))
            if self._encryption_key:
                self._conn.execute(
                    f"PRAGMA key = \"x'{self._encryption_key.hex()}'\""
                )
            self._conn.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL;")
            self._conn.execute("PRAGMA foreign_keys=ON;")
            logger.info("Database connected: %s", self.db_path)
        except sqlite3.Error:
            self._conn = None
            logger.exception("Database connection failed: %s", self.db_path)

    @property
    def is_open(self) -> bool:
        return self._conn is not None

    @property
    def encrypted(self) -> bool:
        return self._encryption_key is not None

    def set_encryption_key(self, encryption_key: bytes | None) -> None:
        if self._conn is not None:
            raise RuntimeError("Close the database before changing its encryption key.")
        self._encryption_key = bytes(encryption_key) if encryption_key else None

    def reopen(self) -> None:
        if self._conn is None:
            self._connect()
        if self._conn is None:
            raise DatabaseEncryptionError("The Echo database could not be opened.")

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

                CREATE TABLE IF NOT EXISTS confirmed_memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    query TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_confirmed_memories_created
                ON confirmed_memories (created_at DESC);
                """
            )
            self._initialize_search_index()
            self._conn.execute("PRAGMA user_version = 2")
            self._conn.commit()
            logger.info("Database initialized.")
        except sqlite3.Error:
            logger.exception("Database initialization failed.")

    def _initialize_search_index(self) -> None:
        """Create a rebuildable local full-text index without changing source records."""
        if self._conn is None:
            return
        try:
            self._conn.executescript(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS memory_search USING fts5(
                    kind UNINDEXED,
                    record_id UNINDEXED,
                    date UNINDEXED,
                    title,
                    detail,
                    timestamp UNINDEXED,
                    tokenize='unicode61'
                );

                CREATE TRIGGER IF NOT EXISTS app_usage_search_insert AFTER INSERT ON app_usage BEGIN
                    INSERT INTO memory_search(kind, record_id, date, title, detail, timestamp)
                    VALUES ('activity', new.id, new.date, new.app_name, new.window_title, new.start_time);
                END;
                CREATE TRIGGER IF NOT EXISTS app_usage_search_delete AFTER DELETE ON app_usage BEGIN
                    DELETE FROM memory_search WHERE kind = 'activity' AND record_id = old.id;
                END;
                CREATE TRIGGER IF NOT EXISTS manual_note_search_insert AFTER INSERT ON manual_notes BEGIN
                    INSERT INTO memory_search(kind, record_id, date, title, detail, timestamp)
                    VALUES ('note', new.id, new.date, 'Note', new.content, new.created_at);
                END;
                CREATE TRIGGER IF NOT EXISTS manual_note_search_delete AFTER DELETE ON manual_notes BEGIN
                    DELETE FROM memory_search WHERE kind = 'note' AND record_id = old.id;
                END;
                CREATE TRIGGER IF NOT EXISTS confirmed_memory_search_insert AFTER INSERT ON confirmed_memories BEGIN
                    INSERT INTO memory_search(kind, record_id, date, title, detail, timestamp)
                    VALUES ('confirmed', new.id, substr(new.created_at, 1, 10), new.query, new.content, new.created_at);
                END;
                CREATE TRIGGER IF NOT EXISTS confirmed_memory_search_delete AFTER DELETE ON confirmed_memories BEGIN
                    DELETE FROM memory_search WHERE kind = 'confirmed' AND record_id = old.id;
                END;
                """
            )
            indexed = self._conn.execute("SELECT COUNT(*) FROM memory_search").fetchone()[0]
            sources = self._conn.execute(
                "SELECT (SELECT COUNT(*) FROM app_usage) + (SELECT COUNT(*) FROM manual_notes) + "
                "(SELECT COUNT(*) FROM confirmed_memories)"
            ).fetchone()[0]
            if indexed != sources:
                self.rebuild_search_index()
        except sqlite3.OperationalError:
            logger.exception("SQLite full-text search is unavailable; basic search will remain usable.")

    def rebuild_search_index(self) -> None:
        if self._conn is None:
            return
        self._conn.execute("DELETE FROM memory_search")
        self._conn.execute(
            """INSERT INTO memory_search(kind, record_id, date, title, detail, timestamp)
               SELECT 'activity', id, date, app_name, window_title, start_time FROM app_usage"""
        )
        self._conn.execute(
            """INSERT INTO memory_search(kind, record_id, date, title, detail, timestamp)
               SELECT 'note', id, date, 'Note', content, created_at FROM manual_notes"""
        )
        self._conn.execute(
            """INSERT INTO memory_search(kind, record_id, date, title, detail, timestamp)
               SELECT 'confirmed', id, substr(created_at, 1, 10), query, content, created_at
               FROM confirmed_memories"""
        )

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

    def search_memory(
        self,
        query: str,
        *,
        limit: int = 20,
        date: str | None = None,
        kind: str | None = None,
    ) -> list[MemoryEvidence]:
        """Search the complete local history and return inspectable source evidence."""
        if self._conn is None:
            return []
        bounded_limit = max(1, min(limit, 100))
        terms = re.findall(r"[A-Za-z0-9_.-]+|[\u4e00-\u9fff]{2,}", query.strip())
        filters: list[str] = []
        parameters: list[object] = []
        if date:
            filters.append("date = ?")
            parameters.append(date)
        if kind:
            filters.append("kind = ?")
            parameters.append(kind)
        where_suffix = (" AND " + " AND ".join(filters)) if filters else ""
        try:
            if terms:
                expression = " OR ".join(f'\"{term.replace(chr(34), chr(34) * 2)}\"' for term in terms[:12])
                rows = self._conn.execute(
                    f"""SELECT kind, record_id, date, title, detail, timestamp
                        FROM memory_search
                        WHERE memory_search MATCH ?{where_suffix}
                        ORDER BY bm25(memory_search), timestamp DESC LIMIT ?""",
                    (expression, *parameters, bounded_limit),
                ).fetchall()
            else:
                base_where = " WHERE " + " AND ".join(filters) if filters else ""
                rows = self._conn.execute(
                    f"""SELECT kind, record_id, date, title, detail, timestamp
                        FROM memory_search{base_where}
                        ORDER BY timestamp DESC LIMIT ?""",
                    (*parameters, bounded_limit),
                ).fetchall()
            return [MemoryEvidence(**dict(row)) for row in rows]
        except sqlite3.Error:
            logger.exception("Full-text memory search failed; using a local LIKE fallback.")
            pattern = f"%{query.strip()}%"
            rows = self._conn.execute(
                """SELECT 'activity' AS kind, id AS record_id, date, app_name AS title,
                          window_title AS detail, start_time AS timestamp
                   FROM app_usage WHERE app_name LIKE ? OR window_title LIKE ?
                   ORDER BY start_time DESC LIMIT ?""",
                (pattern, pattern, bounded_limit),
            ).fetchall()
            return [MemoryEvidence(**dict(row)) for row in rows]

    def create_confirmed_memory(self, *, query: str, content: str, created_at: str) -> int | None:
        if self._conn is None or not content.strip():
            return None
        try:
            cursor = self._conn.execute(
                "INSERT INTO confirmed_memories(query, content, created_at) VALUES (?, ?, ?)",
                (query.strip(), content.strip(), created_at),
            )
            self._conn.commit()
            return int(cursor.lastrowid)
        except sqlite3.Error:
            logger.exception("Confirmed memory insert failed.")
            return None

    def delete_confirmed_memory(self, memory_id: int) -> bool:
        if self._conn is None:
            return False
        try:
            deleted = self._conn.execute(
                "DELETE FROM confirmed_memories WHERE id = ?", (memory_id,)
            ).rowcount
            self._conn.commit()
            return deleted > 0
        except sqlite3.Error:
            logger.exception("Confirmed memory deletion failed. memory_id=%s", memory_id)
            return False

    def get_confirmed_memories(self, limit: int = 200) -> list[ConfirmedMemory]:
        if self._conn is None:
            return []
        try:
            rows = self._conn.execute(
                """SELECT id, query, content, created_at FROM confirmed_memories
                   ORDER BY created_at DESC LIMIT ?""",
                (max(1, min(limit, 1000)),),
            ).fetchall()
            return [ConfirmedMemory(**dict(row)) for row in rows]
        except sqlite3.Error:
            logger.exception("Confirmed memory query failed.")
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
            return {"app_usage": [], "manual_notes": [], "confirmed_memories": []}
        try:
            usage = self._conn.execute(
                "SELECT * FROM app_usage ORDER BY start_time"
            ).fetchall()
            notes = self._conn.execute(
                "SELECT * FROM manual_notes ORDER BY created_at"
            ).fetchall()
            confirmed = self._conn.execute(
                "SELECT * FROM confirmed_memories ORDER BY created_at"
            ).fetchall()
            return {
                "app_usage": [dict(row) for row in usage],
                "manual_notes": [dict(row) for row in notes],
                "confirmed_memories": [dict(row) for row in confirmed],
            }
        except sqlite3.Error:
            logger.exception("Record export query failed.")
            return {"app_usage": [], "manual_notes": [], "confirmed_memories": []}

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
            self._conn.execute(
                "DELETE FROM confirmed_memories WHERE substr(created_at, 1, 10) = ?", (date,)
            )
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
            if self._encryption_key:
                target.execute(
                    f"PRAGMA key = \"x'{self._encryption_key.hex()}'\""
                )
            self._conn.commit()
            self._conn.backup(target)
            target.commit()
        finally:
            target.close()
