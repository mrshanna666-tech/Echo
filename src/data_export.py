from __future__ import annotations

import json
import base64
import os
import shutil
import struct
import zipfile
from datetime import datetime
from pathlib import Path

from src.config import DATA_DIR
from src.database.db import Database
from src.security import read_protected_bytes
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.argon2 import Argon2id


ENCRYPTED_EXPORT_MAGIC = b"ECHOEXPORT1"
EXPORT_TAG_SIZE = 16
EXPORT_CHUNK_SIZE = 1024 * 1024
ARGON2_MEMORY_KIB = 64 * 1024
ARGON2_ITERATIONS = 3
ARGON2_LANES = 4


def export_all_data(database: Database, destination: Path, password: str | None = None) -> Path:
    """Export local records and generated reports into a portable ZIP archive."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    source_root = database.db_path.parent
    staging = destination.parent / f".export-{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
    portable_zip = destination if password is None else destination.with_suffix(destination.suffix + ".portable.tmp")
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
            if not source.is_file() or source.name in {
                "activity.db", "activity.db-wal", "activity.db-shm", "records.json", ".echo.lock"
            }:
                continue
            if staging in source.parents:
                continue
            relative = source.relative_to(source_root)
            if relative.parts and relative.parts[0] in {"security", "backups", "logs"}:
                continue
            if source.suffix.lower() == ".enc":
                relative = relative.with_suffix("")
            target = staging / "files" / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            if source.suffix.lower() == ".enc":
                target.write_bytes(read_protected_bytes(source))
            else:
                shutil.copy2(source, target)
        with zipfile.ZipFile(portable_zip, "w", zipfile.ZIP_DEFLATED) as archive:
            for file in staging.rglob("*"):
                if file.is_file():
                    archive.write(file, file.relative_to(staging).as_posix())
        if password is not None:
            encrypt_portable_export(portable_zip, destination, password)
        return destination
    finally:
        shutil.rmtree(staging, ignore_errors=True)
        if password is not None:
            portable_zip.unlink(missing_ok=True)


def encrypt_portable_export(source_zip: Path, destination: Path, password: str) -> Path:
    if len(password) < 10:
        raise ValueError("Export password must contain at least 10 characters.")
    salt = os.urandom(16)
    nonce = os.urandom(12)
    key = Argon2id(
        salt=salt,
        length=32,
        iterations=ARGON2_ITERATIONS,
        lanes=ARGON2_LANES,
        memory_cost=ARGON2_MEMORY_KIB,
    ).derive(password.encode("utf-8"))
    header = json.dumps(
        {
            "version": 1,
            "cipher": "AES-256-GCM",
            "kdf": "Argon2id",
            "memory_kib": ARGON2_MEMORY_KIB,
            "iterations": ARGON2_ITERATIONS,
            "lanes": ARGON2_LANES,
            "salt": base64.b64encode(salt).decode("ascii"),
            "nonce": base64.b64encode(nonce).decode("ascii"),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    encryptor = Cipher(algorithms.AES(key), modes.GCM(nonce)).encryptor()
    encryptor.authenticate_additional_data(header)
    with Path(source_zip).open("rb") as source, temporary.open("wb") as target:
        target.write(ENCRYPTED_EXPORT_MAGIC)
        target.write(struct.pack(">I", len(header)))
        target.write(header)
        while chunk := source.read(EXPORT_CHUNK_SIZE):
            target.write(encryptor.update(chunk))
        target.write(encryptor.finalize())
        target.write(encryptor.tag)
    temporary.replace(destination)
    return destination


def decrypt_portable_export(source: Path, destination_zip: Path, password: str) -> Path:
    """Decrypt an Echo password export; used by restore tooling and tests."""
    with Path(source).open("rb") as encrypted:
        if encrypted.read(len(ENCRYPTED_EXPORT_MAGIC)) != ENCRYPTED_EXPORT_MAGIC:
            raise ValueError("Not an Echo encrypted export.")
        header_size = struct.unpack(">I", encrypted.read(4))[0]
        if not 1 <= header_size <= 4096:
            raise ValueError("Invalid Echo export header size.")
        header = encrypted.read(header_size)
        metadata = json.loads(header.decode("utf-8"))
        if (
            metadata.get("version") != 1
            or metadata.get("cipher") != "AES-256-GCM"
            or metadata.get("kdf") != "Argon2id"
            or int(metadata.get("memory_kib", 0)) != ARGON2_MEMORY_KIB
            or int(metadata.get("iterations", 0)) != ARGON2_ITERATIONS
            or int(metadata.get("lanes", 0)) != ARGON2_LANES
        ):
            raise ValueError("Unsupported Echo export parameters.")
        salt = base64.b64decode(metadata["salt"])
        nonce = base64.b64decode(metadata["nonce"])
        key = Argon2id(
            salt=salt,
            length=32,
            iterations=int(metadata["iterations"]),
            lanes=int(metadata["lanes"]),
            memory_cost=int(metadata["memory_kib"]),
        ).derive(password.encode("utf-8"))
        ciphertext_start = encrypted.tell()
        encrypted.seek(0, 2)
        ciphertext_end = encrypted.tell() - EXPORT_TAG_SIZE
        encrypted.seek(ciphertext_end)
        tag = encrypted.read(EXPORT_TAG_SIZE)
        encrypted.seek(ciphertext_start)
        decryptor = Cipher(algorithms.AES(key), modes.GCM(nonce, tag)).decryptor()
        decryptor.authenticate_additional_data(header)
        temporary = destination_zip.with_suffix(destination_zip.suffix + ".tmp")
        try:
            with temporary.open("wb") as target:
                remaining = ciphertext_end - ciphertext_start
                while remaining:
                    chunk = encrypted.read(min(EXPORT_CHUNK_SIZE, remaining))
                    if not chunk:
                        raise ValueError("Encrypted export is truncated.")
                    remaining -= len(chunk)
                    target.write(decryptor.update(chunk))
                target.write(decryptor.finalize())
            temporary.replace(destination_zip)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
    return destination_zip


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
