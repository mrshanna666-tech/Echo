from __future__ import annotations

import json
import logging
import os
import base64
import hashlib
import hmac
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from src.config import DATA_DIR


logger = logging.getLogger(__name__)
SECURITY_DIR_NAME = "security"
MASTER_KEY_FILE_NAME = "master-key.dpapi"
STATE_FILE_NAME = "state.json"
ENCRYPTED_FILE_MAGIC = b"ECHOENC1"
NONCE_SIZE = 12
RECOVERY_KEY_PREFIX = "ECHO-RK1-"
RECOVERY_CHECKSUM_SIZE = 4


class SecurityError(RuntimeError):
    pass


@dataclass(frozen=True)
class SecurityState:
    enabled: bool
    locked: bool
    version: int = 1


def _protect_with_dpapi(value: bytes) -> bytes:
    try:
        import win32crypt

        protected = win32crypt.CryptProtectData(
            value,
            "Echo Recorder master key",
            None,
            None,
            None,
            0,
        )
        if isinstance(protected, tuple):
            protected = protected[-1]
        return bytes(protected)
    except Exception as exc:
        raise SecurityError("Windows could not protect the Echo master key.") from exc


def _unprotect_with_dpapi(value: bytes) -> bytes:
    try:
        import win32crypt

        plaintext = win32crypt.CryptUnprotectData(
            value,
            None,
            None,
            None,
            0,
        )
        if isinstance(plaintext, tuple):
            plaintext = plaintext[-1]
        return bytes(plaintext)
    except Exception as exc:
        raise SecurityError("Windows could not unlock the Echo master key.") from exc


class SecurityManager:
    """Owns the in-memory master key and encrypts non-database local files."""

    def __init__(
        self,
        data_dir: Path = DATA_DIR,
        *,
        protect: Callable[[bytes], bytes] = _protect_with_dpapi,
        unprotect: Callable[[bytes], bytes] = _unprotect_with_dpapi,
    ) -> None:
        self.data_dir = Path(data_dir)
        self.security_dir = self.data_dir / SECURITY_DIR_NAME
        self.master_key_path = self.security_dir / MASTER_KEY_FILE_NAME
        self.state_path = self.security_dir / STATE_FILE_NAME
        self._protect = protect
        self._unprotect = unprotect
        self._master_key: bytearray | None = None

    @property
    def enabled(self) -> bool:
        return bool(self._read_state().get("enabled")) and self.master_key_path.exists()

    @property
    def locked(self) -> bool:
        return self.enabled and self._master_key is None

    @property
    def state(self) -> SecurityState:
        payload = self._read_state()
        return SecurityState(
            enabled=self.enabled,
            locked=self.locked,
            version=int(payload.get("version", 1)),
        )

    def provision(self) -> bytes:
        """Create and persist a protected key without marking migration complete."""
        if self.master_key_path.exists():
            return self.unlock()
        key = AESGCM.generate_key(bit_length=256)
        protected = self._protect(key)
        self.security_dir.mkdir(parents=True, exist_ok=True)
        self._atomic_write(self.master_key_path, protected)
        self._write_state({"enabled": False, "version": 1})
        self._master_key = bytearray(key)
        return key

    def activate(self) -> None:
        if self._master_key is None or not self.master_key_path.exists():
            raise SecurityError("The Echo master key is not available.")
        self._write_state({"enabled": True, "version": 1})

    def abort_provision(self) -> None:
        if self.enabled:
            return
        self.lock()
        self.master_key_path.unlink(missing_ok=True)
        self.state_path.unlink(missing_ok=True)

    def unlock(self) -> bytes:
        if self._master_key is not None:
            return bytes(self._master_key)
        if not self.master_key_path.exists():
            raise SecurityError("Echo data protection has not been enabled.")
        key = self._unprotect(self.master_key_path.read_bytes())
        if len(key) != 32:
            raise SecurityError("The protected Echo master key is invalid.")
        self._master_key = bytearray(key)
        return key

    def lock(self) -> None:
        if self._master_key is not None:
            for index in range(len(self._master_key)):
                self._master_key[index] = 0
        self._master_key = None

    def database_key(self) -> bytes:
        return self._derive_key("database")

    def attachment_key(self) -> bytes:
        return self._derive_key("attachments")

    def recovery_key(self) -> str:
        """Return an offline recovery code containing the random master key plus checksum."""
        master = self._require_master_key()
        checksum = hashlib.sha256(b"Echo Recorder recovery/v1" + master).digest()[:RECOVERY_CHECKSUM_SIZE]
        encoded = base64.b32encode(master + checksum).decode("ascii").rstrip("=")
        grouped = "-".join(encoded[index : index + 4] for index in range(0, len(encoded), 4))
        return RECOVERY_KEY_PREFIX + grouped

    def use_recovery_key(self, recovery_key: str) -> bytes:
        """Load a recovery key into memory without overwriting the DPAPI wrapper yet."""
        compact = "".join(character for character in recovery_key.upper() if character.isalnum())
        prefix = "".join(character for character in RECOVERY_KEY_PREFIX if character.isalnum())
        if compact.startswith(prefix):
            compact = compact[len(prefix) :]
        try:
            padded = compact + "=" * (-len(compact) % 8)
            payload = base64.b32decode(padded, casefold=True)
        except Exception as exc:
            raise SecurityError("The Echo recovery key format is invalid.") from exc
        if len(payload) != 32 + RECOVERY_CHECKSUM_SIZE:
            raise SecurityError("The Echo recovery key length is invalid.")
        master, checksum = payload[:32], payload[32:]
        expected = hashlib.sha256(b"Echo Recorder recovery/v1" + master).digest()[:RECOVERY_CHECKSUM_SIZE]
        if not hmac.compare_digest(checksum, expected):
            raise SecurityError("The Echo recovery key checksum is invalid.")
        self.lock()
        self._master_key = bytearray(master)
        return master

    def persist_recovered_key(self) -> None:
        """Re-wrap a verified in-memory recovery key for the current Windows user."""
        if self._master_key is None:
            raise SecurityError("No recovered master key is available.")
        self.security_dir.mkdir(parents=True, exist_ok=True)
        self._atomic_write(self.master_key_path, self._protect(bytes(self._master_key)))

    def encrypt_file(self, source: Path) -> Path:
        source = Path(source)
        if source.suffix.lower() == ".enc":
            return source
        destination = source.with_suffix(source.suffix + ".enc")
        self.write_encrypted(destination, source.read_bytes())
        source.unlink()
        return destination

    def write_encrypted(self, destination: Path, plaintext: bytes) -> Path:
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        nonce = os.urandom(NONCE_SIZE)
        ciphertext = AESGCM(self.attachment_key()).encrypt(
            nonce,
            plaintext,
            ENCRYPTED_FILE_MAGIC,
        )
        self._atomic_write(destination, ENCRYPTED_FILE_MAGIC + nonce + ciphertext)
        return destination

    def decrypt_file(self, source: Path) -> bytes:
        payload = Path(source).read_bytes()
        if not payload.startswith(ENCRYPTED_FILE_MAGIC):
            raise SecurityError("This file is not an Echo encrypted attachment.")
        offset = len(ENCRYPTED_FILE_MAGIC)
        nonce = payload[offset : offset + NONCE_SIZE]
        ciphertext = payload[offset + NONCE_SIZE :]
        try:
            return AESGCM(self.attachment_key()).decrypt(
                nonce,
                ciphertext,
                ENCRYPTED_FILE_MAGIC,
            )
        except Exception as exc:
            raise SecurityError("The encrypted attachment could not be authenticated.") from exc

    def migrate_attachments(self) -> list[tuple[Path, Path]]:
        """Encrypt existing user-authored photos, reflections, and mood journals."""
        migrated: list[tuple[Path, Path]] = []
        if not self.data_dir.exists():
            return migrated
        excluded_roots = {self.security_dir.resolve(), (self.data_dir / "backups").resolve()}
        for path in self.data_dir.rglob("*"):
            if not path.is_file() or not (
                path.suffix.lower() in {".jpg", ".jpeg", ".png", ".md"}
                or path.name == "daily.json"
            ):
                continue
            resolved = path.resolve()
            if any(root == resolved or root in resolved.parents for root in excluded_roots):
                continue
            try:
                destination = self.encrypt_file(path)
                migrated.append((path, destination))
            except Exception:
                logger.exception("Could not encrypt attachment during migration: %s", path)
        return migrated

    def _derive_key(self, purpose: str) -> bytes:
        master = self._require_master_key()
        return HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=None,
            info=f"Echo Recorder/{purpose}/v1".encode("utf-8"),
        ).derive(master)

    def _require_master_key(self) -> bytes:
        if self._master_key is None:
            raise SecurityError("Echo data is locked.")
        return bytes(self._master_key)

    def _read_state(self) -> dict[str, object]:
        try:
            if not self.state_path.exists():
                return {"enabled": False, "version": 1}
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else {"enabled": False, "version": 1}
        except Exception:
            logger.exception("Failed to read Echo security state.")
            return {"enabled": False, "version": 1}

    def _write_state(self, payload: dict[str, object]) -> None:
        self.security_dir.mkdir(parents=True, exist_ok=True)
        self._atomic_write(
            self.state_path,
            json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"),
        )

    @staticmethod
    def _atomic_write(destination: Path, payload: bytes) -> None:
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        temporary.write_bytes(payload)
        temporary.replace(destination)


_security_manager: SecurityManager | None = None


def get_security_manager() -> SecurityManager:
    global _security_manager
    if _security_manager is None or _security_manager.data_dir != DATA_DIR:
        _security_manager = SecurityManager(DATA_DIR)
    return _security_manager


def protected_path(path: Path) -> Path:
    path = Path(path)
    if path.suffix.lower() == ".enc":
        return path
    encrypted = path.with_suffix(path.suffix + ".enc")
    manager = get_security_manager()
    if encrypted.exists():
        return encrypted
    if path.exists():
        return path
    return encrypted if manager.enabled else path


def read_protected_bytes(path: Path) -> bytes:
    actual = protected_path(path)
    if actual.suffix.lower() == ".enc":
        return get_security_manager().decrypt_file(actual)
    return actual.read_bytes()


def read_protected_text(path: Path, encoding: str = "utf-8") -> str:
    return read_protected_bytes(path).decode(encoding)


def write_protected_bytes(path: Path, payload: bytes) -> Path:
    path = Path(path)
    manager = get_security_manager()
    if not manager.enabled:
        path.parent.mkdir(parents=True, exist_ok=True)
        SecurityManager._atomic_write(path, payload)
        return path
    destination = path if path.suffix.lower() == ".enc" else path.with_suffix(path.suffix + ".enc")
    manager.write_encrypted(destination, payload)
    if destination != path:
        path.unlink(missing_ok=True)
    return destination


def write_protected_text(path: Path, value: str, encoding: str = "utf-8") -> Path:
    return write_protected_bytes(path, value.encode(encoding))
