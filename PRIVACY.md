# Privacy

Echo is designed as a local-first Windows activity journal.

## Data handling

- Activity history, notes, mood entries, photos, preferences, and generated summaries stay on the user's device by default.
- Optional Data protection encrypts the activity database and search index with SQLCipher, user-authored files with AES-256-GCM, and protects the master key with Windows DPAPI.
- Internal backups remain encrypted. Portable ZIP exports are readable decrypted copies created only after an explicit warning and never include the protected master key.
- Password-encrypted `.echoexport` packages are available as the preferred portable export. Echo does not store the export password.
- Optional auto-lock pauses recording, closes the database, clears the in-memory key, and discards rendered private content after the configured Windows idle period.
- Recovery keys are shown or saved only on explicit request. They provide full access to encrypted Echo data and must be stored offline.
- AI reflection is disabled by default. Local reflection generation never makes a network request.
- Before an AI reflection request, Echo displays the exact sanitized categories that may be sent and requires confirmation for that request.
- AI requests contain only the date, aggregate app durations, and total duration. Window titles, local paths, email addresses, URLs, IP addresses, photos, and raw activity events are excluded.
- Manual notes are excluded unless the user enables the separate notes option. Even then, common identifiers are removed before the preview and request are created.
- The OpenAI API key is read from `OPENAI_API_KEY` or stored in Windows Credential Manager under `EchoRecorder/OpenAI`. It is never written to preferences, logs, exports, summaries, or source control.
- If an AI request fails, Echo creates a local reflection instead and does not retry or send additional data automatically.
- Recognizable API and source-control tokens are replaced before a window title is stored. Window titles are never written to Echo's diagnostic log.
- `--demo` mode pauses activity recording and uses an isolated synthetic database under the Windows temporary directory; it does not read or modify the normal Echo database.
- Echo does not require these personal records to be committed to source control.
- The repository ignore rules exclude the `data/` and `logs/` directories, SQLite databases, local preferences, screenshots, recordings, secrets, and environment files.
- Contributors must use synthetic data in tests, screenshots, demos, and documentation.

## Before publishing or sharing

1. Run `git status --short --ignored` and confirm that local data remains ignored.
2. Search staged files for email addresses, names, access tokens, API keys, passwords, window titles, and filesystem paths.
3. Never commit `.env` files, database files, logs, personal photos, exports, or real activity summaries.
4. Revoke and rotate any credential immediately if it is accidentally committed.
5. Use synthetic app names and notes when testing the AI preview or recording a demo.

## Reporting a privacy issue

Do not include personal data or secrets in a public issue. Contact the repository owner privately and provide only the minimum information needed to reproduce the problem.
