from pathlib import Path


APP_NAME = "Echo Recorder"
POLL_INTERVAL_MS = 3000
MAX_POLL_GAP_SECONDS = 30
MIN_ACTIVITY_SECONDS = 5

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
LOG_DIR = ROOT_DIR / "logs"
DOCS_DIR = ROOT_DIR / "docs"
DB_PATH = DATA_DIR / "activity.db"
ERROR_LOG_PATH = LOG_DIR / "error.log"
INSTANCE_LOCK_PATH = DATA_DIR / ".echo.lock"


def ensure_app_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
