import sys
import types
import unittest
from unittest.mock import patch

from src.openai_key_store import load_openai_api_key, save_openai_api_key


class OpenAiKeyStoreTests(unittest.TestCase):
    def test_credential_blob_is_written_as_unicode(self):
        written = {}
        fake = types.SimpleNamespace(
            CRED_TYPE_GENERIC=1,
            CRED_PERSIST_LOCAL_MACHINE=2,
            CredWrite=lambda credential, flags: written.update(credential),
        )
        with patch.dict(sys.modules, {"win32cred": fake}):
            save_openai_api_key("sk-" + ("example" * 5))

        self.assertIsInstance(written["CredentialBlob"], str)

    def test_unicode_credential_blob_round_trip(self):
        fake = types.SimpleNamespace(
            CRED_TYPE_GENERIC=1,
            CredRead=lambda target, credential_type, flags: {
                "CredentialBlob": "sk-synthetic-test-key"
            },
        )
        with (
            patch.dict(sys.modules, {"win32cred": fake}),
            patch.dict("os.environ", {}, clear=True),
        ):
            self.assertEqual(load_openai_api_key(), "sk-synthetic-test-key")


if __name__ == "__main__":
    unittest.main()
