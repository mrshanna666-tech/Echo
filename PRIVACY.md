# Privacy

Echo is designed as a local-first Windows activity journal.

## Data handling

- Activity history, notes, mood entries, photos, preferences, and generated summaries stay on the user's device by default.
- Echo does not require these personal records to be committed to source control.
- The repository ignore rules exclude the `data/` and `logs/` directories, SQLite databases, local preferences, screenshots, recordings, secrets, and environment files.
- Contributors must use synthetic data in tests, screenshots, demos, and documentation.

## Before publishing or sharing

1. Run `git status --short --ignored` and confirm that local data remains ignored.
2. Search staged files for email addresses, names, access tokens, API keys, passwords, window titles, and filesystem paths.
3. Never commit `.env` files, database files, logs, personal photos, exports, or real activity summaries.
4. Revoke and rotate any credential immediately if it is accidentally committed.

## Reporting a privacy issue

Do not include personal data or secrets in a public issue. Contact the repository owner privately and provide only the minimum information needed to reproduce the problem.

