# Echo Recorder

Echo Recorder is a privacy-first Windows desktop activity journal that helps people reconstruct their day without sending personal activity data to a cloud service.

## What Echo does

- Records foreground application activity locally
- Presents a daily timeline and activity overview
- Supports manual notes and mood journaling
- Replays nearby activity and notes around a selected moment
- Explores local activity and notes in a zoomable memory atlas, with app constellations and source-linked replay
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

## Memory atlas

Open **Memory atlas / 记忆星图** in the sidebar for a full-window 3D space with perspective, layered stardust, and procedural nebulae. Memory stars occupy stable positions in depth. Warm stars represent applications, blue-white stars represent daily activity, and amber stars represent notes. Background dust and clouds are decorative and never count as memories or evidence.

Entering the atlas fades out the previous page, gently approaches the remembered view, and reveals the controls in sequence. Dragging or scrolling can take over immediately. Reduced-motion settings show the page directly. Transition snapshots stay in memory only and are released after the entrance, on navigation, or when Echo locks.

- Drag to orbit; right-drag or **Shift + drag** to pan. Scroll, use the zoom buttons, or press **+ / −** to approach or pull back. **Home / 归航** or the **Home** key smoothly pulls back and turns toward the overview. Dragging or scrolling takes control immediately; another return starts from the current camera pose.
- **Explore / 探索** opens the normally hidden filters. Choose a 7-, 30-, or 90-day period ending on a selected date, then filter by application, notes, or search text.
- Click a star to fly closer and open its floating source details. **Return to this moment / 回到这一刻** opens Memory replay at the recorded date and time.
- Use the arrow keys or **Star list / 星点列表** to select stars without pointing at the canvas.
- **Drift / 漫游** toggles slow camera orbit. **Immerse / 沉浸** hides the page chrome and idle labels; **Show interface / 显示界面** restores them. **F11** or **Fullscreen / 全屏** toggles fullscreen.
- **Back to Echo / 返回 Echo** restores the main navigation. **Escape** closes filters or source details first, then leaves immersive mode, fullscreen, or the atlas. Leaving the atlas restores the previous window mode.

The overview shows up to eight applications ranked by recorded duration, twelve recent recorded days per application, and forty recent notes. Selecting an application expands its days across the chosen period. Search can uncover earlier matching notes within the loaded period; source details show the latest twenty records for a selected star. Loading is limited to the latest 20,000 records of each type in the chosen period, with an explanation when narrowing the range is needed.

App constellations connect recorded days within the same application. Notes connect to the nearest visible activity on the same day only when it is within thirty minutes; independent notes remain unconnected. These links describe recorded proximity, not inferred projects or causality. Depth is a visual arrangement and adds no inferred relationships. The atlas is generated entirely on-device and its rendered contents are cleared when Echo locks. Camera drift pauses during selection and interaction; animation stops when hidden or locked. Reduced-motion preferences disable drift and make camera focus immediate.

Rendering uses native Qt OpenGL with bundled procedural shaders and no browser, CDN, downloaded textures, or extra Python packages. If OpenGL is unavailable, a painter renderer preserves the same 3D camera, source stars, and picking, with fewer decorative particles. Headless QA uses this fallback automatically.

To explore an isolated synthetic atlas without recording activity or reading the normal Echo database:

```powershell
.\.venv\Scripts\python scripts\preview_memory_star_map.py --interactive
```

Add `--start-home` to start this isolated demo on Home and try entering the atlas from its sidebar:

```powershell
.\.venv\Scripts\python scripts\preview_memory_star_map.py --interactive --start-home
```

To generate QA captures and check replay and return navigation without opening an interactive window:

```powershell
.\.venv\Scripts\python scripts\preview_memory_star_map.py
```

To verify the native OpenGL renderer, fullscreen transitions, and captures in a temporary desktop window:

```powershell
.\.venv\Scripts\python scripts\preview_memory_star_map.py --native-capture
```

The preview uses temporary synthetic data under `build/atlas-preview/`. Captures are written to `screenshots/memory-atlas.png`, with `-compact`, `-orbit`, `-immersive`, and `-detail` variants. The script prints the renderer actually used. The `screenshots/` directory is ignored by Git; keep real data and generated screenshot files out of commits.

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
