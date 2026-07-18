# Echo Recorder

Echo Recorder is a privacy-first Windows desktop activity journal that helps people reconstruct their day without sending personal activity data to a cloud service.

## What Echo does

- Records foreground application activity locally
- Presents a daily timeline and activity overview
- Supports manual notes and mood journaling
- Replays nearby activity and notes around a selected moment
- Generates local daily reflections, with an optional privacy-reviewed GPT-5.6 mode
- Switches between Simplified Chinese and English
- Provides pause, exclusion, retention, and idle-time controls
- Exports and backs up user-owned data

## Privacy by default

Echo stores activity records, notes, preferences, and generated summaries under the local `data/` directory. These records are intentionally excluded from version control. Logs, screenshots, databases, photos, exports, environment files, and secrets must never be committed.

See [PRIVACY.md](PRIVACY.md) and [SECURITY.md](SECURITY.md) before sharing code or test material.

The AI reflection feature is off by default. When enabled, Echo shows a sanitized preview before every request and sends nothing unless the user explicitly confirms. Window titles, filesystem paths, email addresses, URLs, photos, and raw activity records are excluded. Manual notes remain excluded unless the user separately opts in. The OpenAI API key is stored in Windows Credential Manager, not in the repository or preferences file.

## Requirements

- Windows 10 or later
- Python 3.12 or later
- PySide6
- pywin32

## Run from source

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
.\.venv\Scripts\python main.py
```

Echo starts in the Windows system tray. Use the tray menu to open the main window, add a note, pause or resume recording, open the local data folder, or exit.

Language and the optional AI reflection mode can be changed under **Settings**. Changing the language rebuilds the main window immediately without changing recorded data or the Memory layout.

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

## OpenAI Build Week

Echo existed before the OpenAI Build Week submission period and has been meaningfully extended during the event using Codex and GPT-5.6. The competition work and evidence are documented in [docs/BUILD_WEEK.md](docs/BUILD_WEEK.md).

## Repository status

Echo is under active development. The repository is private and the code is currently all rights reserved.
