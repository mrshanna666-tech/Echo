from pathlib import Path
import tempfile
import unittest
import zipfile

from src.data_export import ENCRYPTED_EXPORT_MAGIC, decrypt_portable_export, export_all_data
from src.database.db import Database
from src.security import SecurityManager
import src.security as security_module


class DataExportTests(unittest.TestCase):
    def test_export_contains_records_json(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            db = Database(root / "activity.db")
            db.initialize()
            db.add_manual_note(
                date="2026-07-17", content="portable note", created_at="2026-07-17 10:00:00",
            )
            output = export_all_data(db, root / "export.zip")
            self.assertTrue(output.exists())
            with zipfile.ZipFile(output) as archive:
                self.assertIn("records.json", archive.namelist())
                self.assertIn("portable note", archive.read("records.json").decode("utf-8"))
            db.close()

    def test_sqlite_backup_contains_wal_records(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            db = Database(root / "activity.db")
            db.initialize()
            db.add_manual_note(
                date="2026-07-17", content="backup note", created_at="2026-07-17 11:00:00",
            )
            backup = root / "backup.db"
            db.backup_to(backup)
            restored = Database(backup)
            restored.initialize()
            self.assertEqual(restored.get_manual_notes_by_date("2026-07-17")[0].content, "backup note")
            restored.close()
            db.close()

    def test_protected_export_decrypts_attachments_and_omits_master_key(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            db = Database(root / "activity.db")
            db.initialize()
            manager = SecurityManager(
                root,
                protect=lambda value: b"wrapped:" + value,
                unprotect=lambda value: value[len(b"wrapped:") :],
            )
            manager.provision()
            manager.activate()
            photo = root / "moods" / "memory.jpg"
            photo.parent.mkdir(parents=True)
            photo.write_bytes(b"private photo")
            encrypted_photo = manager.encrypt_file(photo)
            previous_manager = security_module._security_manager
            previous_data_dir = security_module.DATA_DIR
            security_module.DATA_DIR = root
            security_module._security_manager = manager
            try:
                output = export_all_data(db, root / "export.zip")
            finally:
                security_module._security_manager = previous_manager
                security_module.DATA_DIR = previous_data_dir
            with zipfile.ZipFile(output) as archive:
                self.assertIn("files/moods/memory.jpg", archive.namelist())
                self.assertEqual(archive.read("files/moods/memory.jpg"), b"private photo")
                self.assertNotIn("files/security/master-key.dpapi", archive.namelist())
                self.assertNotIn(encrypted_photo.name, archive.namelist())
            db.close()

    def test_password_export_round_trip_and_wrong_password_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            db = Database(root / "activity.db")
            db.initialize()
            db.add_manual_note(
                date="2026-07-31", content="encrypted portable note", created_at="2026-07-31 10:00:00",
            )
            encrypted = export_all_data(db, root / "portable.echoexport", password="correct horse battery")
            self.assertTrue(encrypted.read_bytes().startswith(ENCRYPTED_EXPORT_MAGIC))
            restored_zip = decrypt_portable_export(encrypted, root / "restored.zip", "correct horse battery")
            with zipfile.ZipFile(restored_zip) as archive:
                self.assertIn("encrypted portable note", archive.read("records.json").decode("utf-8"))
            with self.assertRaises(Exception):
                decrypt_portable_export(encrypted, root / "wrong.zip", "wrong password value")
            self.assertFalse((root / "wrong.zip").exists())
            db.close()


if __name__ == "__main__":
    unittest.main()
