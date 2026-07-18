from __future__ import annotations

import os

from src.preferences import load_preferences


SUPPORTED_LANGUAGES = {"zh-CN", "en"}


def current_language() -> str:
    environment_language = os.environ.get("ECHO_LANGUAGE", "")
    if environment_language in SUPPORTED_LANGUAGES:
        return environment_language
    language = load_preferences().language
    return language if language in SUPPORTED_LANGUAGES else "zh-CN"


def tr(zh_cn: str, english: str, language: str | None = None) -> str:
    return english if (language or current_language()) == "en" else zh_cn
