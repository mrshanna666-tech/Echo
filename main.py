import os
import sys
import tempfile
from pathlib import Path


if "--demo" in sys.argv:
    sys.argv.remove("--demo")
    os.environ["ECHO_DEMO_MODE"] = "1"
    os.environ["ECHO_DATA_DIR"] = str(Path(tempfile.gettempdir()) / "EchoRecorderDemo")
    os.environ.setdefault("ECHO_LANGUAGE", "en")

from src.app import main  # noqa: E402 - demo environment must be set first


if __name__ == "__main__":
    main()
