# Echo Recorder

Echo Recorder is a privacy-first Windows desktop activity journal that helps people reconstruct their day without sending personal activity data to a cloud service.

## What Echo does

- Records foreground application activity locally
- Presents a daily timeline and activity overview
- Supports manual notes and mood journaling
- Replays nearby activity and notes around a selected moment
- Searches the complete local history with ranked, inspectable evidence
- Deep-links answers back to the matching timeline and supports reversible user-confirmed corrections
- Generates local daily reflections, with an optional privacy-reviewed GPT-5.6 mode
- Switches between Simplified Chinese and English
- Provides pause, exclusion, retention, and idle-time controls
- Exports and backs up user-owned data
- Optionally encrypts the database, search index, photos, journals, and reflections at rest

## Privacy by default

Echo stores activity records, notes, preferences, and generated summaries under the local `data/` directory. These records are intentionally excluded from version control. Logs, screenshots, databases, photos, exports, environment files, and secrets must never be committed.

See [PRIVACY.md](PRIVACY.md) and [SECURITY.md](SECURITY.md) before sharing code or test material.

Data protection can be enabled under **Settings**. Echo migrates the database and FTS index to SQLCipher, encrypts user-authored files with AES-256-GCM, and protects the master key with Windows DPAPI. It can auto-lock after Windows is idle, clears rendered private data on lock, and supports an offline recovery key. Internal database backups remain encrypted. Portable exports can be either a readable ZIP or a password-encrypted `.echoexport` package using Argon2id and AES-256-GCM.

The AI reflection feature is off by default. When enabled, Echo shows a sanitized preview before every request and sends nothing unless the user explicitly confirms. Window titles, filesystem paths, email addresses, URLs, photos, and raw activity records are excluded. Manual notes remain excluded unless the user separately opts in. The OpenAI API key is stored in Windows Credential Manager, not in the repository or preferences file.

## Requirements

- Windows 10 or later
- Python 3.12 or later
- PySide6
- pywin32
- cryptography 45.x
- sqlcipher3 0.6.2

## Run from source

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
.\.venv\Scripts\python main.py
```

Echo starts in the Windows system tray. Use the tray menu to open the main window, add a note, pause or resume recording, open the local data folder, or exit.

Language and the optional AI reflection mode can be changed under **Settings**. Changing the language rebuilds the main window immediately without changing recorded data or the Memory layout.

## Privacy-safe demo mode

Run Echo with a complete synthetic day:

```powershell
.\.venv\Scripts\python main.py --demo
```

Demo mode stores its temporary database, preferences, logs, and generated reflections under the Windows temporary directory in `EchoRecorderDemo`. It pauses activity recording, never reads the normal Echo database, and makes no API request unless a tester separately configures a key and explicitly confirms the sanitized preview. Each launch resets the synthetic day.

## Run tests

```powershell
.\.venv\Scripts\python -m unittest discover -s tests -v
```

## Build a Windows executable

Install PyInstaller, then build with the included specification:

```powershell
.\.venv\Scripts\pip install pyinstaller
.\.venv\Scripts\pyinstaller --clean echo.spec
```

The resulting `dist\EchoRecorder.exe` also accepts `--demo`, giving judges a no-setup testing path with synthetic data.

## OpenAI Build Week

Echo existed before the OpenAI Build Week submission period and has been meaningfully extended during the event using Codex and GPT-5.6. The competition work and evidence are documented in [docs/BUILD_WEEK.md](docs/BUILD_WEEK.md).

## Repository status

Echo is under active development. The repository is private and the code is currently all rights reserved.
