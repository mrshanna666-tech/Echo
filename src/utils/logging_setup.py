from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from src.config import ERROR_LOG_PATH, LOG_DIR


def setup_logging() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.handlers.clear()

    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

    error_handler = RotatingFileHandler(
        ERROR_LOG_PATH,
        maxBytes=2 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    error_handler.setLevel(logging.INFO)
    error_handler.setFormatter(formatter)
    root_logger.addHandler(error_handler)
