# Security Policy

Echo records sensitive local activity metadata. Security and privacy regressions should be treated as high priority.

## Supported version

The latest version on the default branch is supported during active development.

## Reporting

Please report vulnerabilities privately to the repository owner. Do not post credentials, personal activity records, screenshots, databases, logs, or identifying window titles in an issue.

## Development rules

- Use synthetic fixtures and test databases.
- Keep user data outside the repository.
- Do not add telemetry or network transmission without explicit, documented user consent.
- Minimize stored window-title data and provide exclusion controls.
- Validate exports so users understand what personal information they contain.

## Data protection

When enabled in Settings, Echo uses SQLCipher for the SQLite database and FTS index, AES-256-GCM for photos, mood journals, and reflections, and Windows DPAPI to wrap the 256-bit master key. Purpose-specific database and attachment keys are derived with HKDF-SHA-256. Encrypted attachments are authenticated before they are displayed and are decoded in memory.

Enabling protection creates a migration backup before replacing the plaintext database. The backup is encrypted after a successful migration. Locking pauses recording, closes the database connection, clears the in-memory master key, and restricts navigation to Settings. Portable ZIP export is a deliberate decrypted copy and requires a warning confirmation.

Auto-lock uses the Windows-wide last-input time and is configurable from Settings. Locking also discards the current window tree so rendered notes, photos, search results, and reflections are not left accessible in the UI. Key derivation refuses to silently reload the DPAPI key while the app is locked.

The optional recovery code contains the random master key plus a versioned checksum. Echo never stores this code separately; anyone who obtains it can decrypt the protected data. Password-encrypted `.echoexport` files derive a 256-bit key with Argon2id (64 MiB, three iterations, four lanes) and authenticate the complete archive and metadata with AES-256-GCM. A readable ZIP can be recovered from Settings with the export password.
