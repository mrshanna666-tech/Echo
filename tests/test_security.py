from pathlib import Path
import sqlite3 as plaintext_sqlite3
import tempfile
import unittest

from src.database.db import Database, migrate_plaintext_database
from src.security import ENCRYPTED_FILE_MAGIC, SecurityError, SecurityManager


def _protect(value: bytes) -> bytes:
    return b"test-wrapper:" + value


def _unprotect(value: bytes) -> bytes:
    if not value.startswith(b"test-wrapper:"):
        raise ValueError("invalid wrapper")
    return value[len(b"test-wrapper:") :]


class SecurityTests(unittest.TestCase):
    def test_master_key_locks_and_unlocks_through_protector(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = SecurityManager(Path(directory), protect=_protect, unprotect=_unprotect)
            original = manager.provision()
            manager.activate()

            self.assertTrue(manager.enabled)
            self.assertFalse(manager.locked)
            manager.lock()
            self.assertTrue(manager.locked)
            self.assertEqual(manager.unlock(), original)

    def test_attachment_encryption_is_authenticated_and_removes_plaintext(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manager = SecurityManager(root, protect=_protect, unprotect=_unprotect)
            manager.provision()
            manager.activate()
            source = root / "memory.jpg"
            source.write_bytes(b"private photo bytes")

            encrypted = manager.encrypt_file(source)

            self.assertFalse(source.exists())
            self.assertTrue(encrypted.read_bytes().startswith(ENCRYPTED_FILE_MAGIC))
            self.assertEqual(manager.decrypt_file(encrypted), b"private photo bytes")
            manager.lock()
            with self.assertRaises(SecurityError):
                manager.decrypt_file(encrypted)
            manager.unlock()
            payload = bytearray(encrypted.read_bytes())
            payload[-1] ^= 1
            encrypted.write_bytes(payload)
            with self.assertRaises(Exception):
                manager.decrypt_file(encrypted)

    def test_recovery_key_restores_the_same_master_key_and_can_be_rewrapped(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manager = SecurityManager(root, protect=_protect, unprotect=_unprotect)
            original = manager.provision()
            manager.activate()
            recovery_key = manager.recovery_key()
            manager.master_key_path.write_bytes(b"unreadable")
            manager.lock()

            recovered = manager.use_recovery_key(recovery_key.lower())
            manager.persist_recovered_key()
            manager.lock()

            self.assertEqual(recovered, original)
            self.assertEqual(manager.unlock(), original)
            invalid_key = recovery_key[:-1] + ("A" if recovery_key[-1] != "A" else "B")
            with self.assertRaises(SecurityError):
                manager.use_recovery_key(invalid_key)

    def test_attachment_migration_includes_daily_journal_and_skips_backups(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manager = SecurityManager(root, protect=_protect, unprotect=_unprotect)
            manager.provision()
            manager.activate()
            journal = root / "2026" / "07" / "31" / "daily.json"
            journal.parent.mkdir(parents=True)
            journal.write_text('{"entries": []}', encoding="utf-8")
            backup = root / "backups" / "activity.db"
            backup.parent.mkdir(parents=True)
            backup.write_bytes(b"backup")

            migrated = manager.migrate_attachments()

            encrypted_journal = journal.with_suffix(".json.enc")
            self.assertIn((journal, encrypted_journal), migrated)
            self.assertFalse(journal.exists())
            self.assertEqual(manager.decrypt_file(encrypted_journal), b'{"entries": []}')
            self.assertTrue(backup.exists())

    def test_plaintext_database_migrates_to_sqlcipher_and_backup_stays_encrypted(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "activity.db"
            database = Database(path)
            database.initialize()
            database.add_manual_note(
                date="2026-07-31",
                content="encrypted Echo note",
                created_at="2026-07-31 12:00:00",
            )
            database.close()

            manager = SecurityManager(root, protect=_protect, unprotect=_unprotect)
            manager.provision()
            key = manager.database_key()
            migrate_plaintext_database(path, key)
            manager.activate()

            self.assertNotEqual(path.read_bytes()[:16], b"SQLite format 3\x00")
            encrypted_database = Database(path, key)
            encrypted_database.initialize()
            self.assertEqual(
                encrypted_database.get_manual_notes_by_date("2026-07-31")[0].content,
                "encrypted Echo note",
            )
            backup = root / "backup.db"
            encrypted_database.backup_to(backup)
            encrypted_database.close()
            self.assertNotEqual(backup.read_bytes()[:16], b"SQLite format 3\x00")
            with self.assertRaises(plaintext_sqlite3.DatabaseError):
                connection = plaintext_sqlite3.connect(backup)
                try:
                    connection.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()
                finally:
                    connection.close()


if __name__ == "__main__":
    unittest.main()
