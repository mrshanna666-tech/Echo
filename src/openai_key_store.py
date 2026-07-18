from __future__ import annotations

import os


_CREDENTIAL_TARGET = "EchoRecorder/OpenAI"


def load_openai_api_key() -> str:
    environment_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if environment_key:
        return environment_key
    try:
        import win32cred

        credential = win32cred.CredRead(
            _CREDENTIAL_TARGET,
            win32cred.CRED_TYPE_GENERIC,
            0,
        )
        blob = credential.get("CredentialBlob", b"")
        if isinstance(blob, bytes):
            try:
                return blob.decode("utf-16-le").rstrip("\x00").strip()
            except UnicodeDecodeError:
                return blob.decode("utf-8").rstrip("\x00").strip()
        return str(blob).strip()
    except Exception:
        return ""


def save_openai_api_key(api_key: str) -> None:
    key = api_key.strip()
    try:
        import win32cred
    except ImportError as exc:
        raise RuntimeError("Windows Credential Manager is unavailable.") from exc

    if not key:
        try:
            win32cred.CredDelete(_CREDENTIAL_TARGET, win32cred.CRED_TYPE_GENERIC, 0)
        except Exception:
            pass
        return

    win32cred.CredWrite(
        {
            "Type": win32cred.CRED_TYPE_GENERIC,
            "TargetName": _CREDENTIAL_TARGET,
            # pywin32's Unicode CredWrite wrapper expects a string here.
            # Passing bytes raises "Objects of type 'bytes' can not be
            # converted to Unicode" on current Windows builds.
            "CredentialBlob": key,
            "Persist": win32cred.CRED_PERSIST_LOCAL_MACHINE,
            "UserName": "Echo Recorder",
        },
        0,
    )
