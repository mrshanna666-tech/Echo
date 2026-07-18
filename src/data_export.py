from __future__ import annotations

import json
import shutil
import zipfile
from datetime import datetime
from pathlib import Path

from src.config import DATA_DIR
from src.database.db import Database


def export_all_data(database: Database, destination: Path) -> Path:
    """Export local records and generated reports into a portable ZIP archive."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    source_root = database.db_path.parent
    staging = destination.parent / f".export-{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
    staging.mkdir(parents=True, exist_ok=False)
    try:
        payload = {
            "exported_at": datetime.now().isoformat(timespec="seconds"),
            **database.export_records(),
        }
        (staging / "records.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        for source in source_root.rglob("*"):
            if not source.is_file() or source.name in {"activity.db", "records.json"}:
                continue
            if staging in source.parents:
                continue
            relative = source.relative_to(source_root)
            target = staging / "files" / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
            for file in staging.rglob("*"):
                if file.is_file():
                    archive.write(file, file.relative_to(staging).as_posix())
        return destination
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def backup_database(database_path: Path) -> Path:
    backup_dir = DATA_DIR / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    target = backup_dir / f"activity-{datetime.now().strftime('%Y%m%d-%H%M%S')}.db"
    # Kept for callers that only have a path; the app uses Database.backup_to
    # so active WAL pages are included in the backup.
    shutil.copy2(database_path, target)
    return target


def backup_database_connection(database, database_path: Path) -> Path:
    """Back up an open Database through SQLite's online backup API."""
    backup_dir = DATA_DIR / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    target = backup_dir / f"activity-{datetime.now().strftime('%Y%m%d-%H%M%S')}.db"
    database.backup_to(target)
    return target
