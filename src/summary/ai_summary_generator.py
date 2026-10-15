from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from collections import defaultdict
from dataclasses import dataclass

from src.database.db import Database
from src.database.models import AppUsage, ManualNote
from src.summary.local_summary_generator import SummaryResult, save_summary_file


MODEL = "gpt-5.6-terra"
RESPONSES_URL = "https://api.openai.com/v1/responses"
_EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_WINDOWS_PATH = re.compile(r"\b[A-Za-z]:\\(?:[^\\\s]+\\)*[^\\\s]*")
_URL = re.compile(r"https?://\S+", re.IGNORECASE)
_IP_ADDRESS = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")


@dataclass(frozen=True)
class SanitizedSummaryPayload:
    date: str
    total_seconds: int
    applications: tuple[dict[str, object], ...]
    notes: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "date": self.date,
            "total_seconds": self.total_seconds,
            "applications": list(self.applications),
            "notes": list(self.notes),
        }


def redact_sensitive_text(value: str) -> str:
    text = _EMAIL.sub("[email removed]", value)
    text = _WINDOWS_PATH.sub("[path removed]", text)
    text = _URL.sub("[link removed]", text)
    text = _IP_ADDRESS.sub("[network address removed]", text)
    return " ".join(text.split())[:500]


def build_sanitized_payload(
    date_text: str,
    app_usage: list[AppUsage],
    manual_notes: list[ManualNote],
    include_notes: bool,
) -> SanitizedSummaryPayload:
    seconds_by_app: dict[str, int] = defaultdict(int)
    for usage in app_usage:
        app_name = redact_sensitive_text(usage.app_name or "Unknown")
        seconds_by_app[app_name] += max(usage.duration_seconds or 0, 0)

    applications = tuple(
        {"name": name, "seconds": seconds}
        for name, seconds in sorted(
            seconds_by_app.items(),
            key=lambda item: item[1],
            reverse=True,
        )[:12]
    )
    notes = (
        tuple(
            note
            for note in (
                redact_sensitive_text(item.content)
                for item in manual_notes[-10:]
            )
            if note
        )
        if include_notes
        else ()
    )
    return SanitizedSummaryPayload(
        date=date_text,
        total_seconds=sum(max(item.duration_seconds or 0, 0) for item in app_usage),
        applications=applications,
        notes=notes,
    )


def build_preview(payload: SanitizedSummaryPayload, language: str, provider: str = "openai") -> str:
    if provider == "local":
        heading = (
            "The following sanitized data will be sent to your local AI service:"
            if language == "en"
            else "以下脱敏数据将发送给你配置的本地 AI 服务："
        )
        privacy = (
            "The data stays on this device unless you configure a non-local server address."
            if language == "en"
            else "除非你自行配置非本地地址，否则数据不会离开此设备。"
        )
        return f"{heading}\n\n{json.dumps(payload.as_dict(), ensure_ascii=False, indent=2)}\n\n{privacy}"
    heading = (
        "The following sanitized data will be sent to GPT-5.6:"
        if language == "en"
        else "以下脱敏数据将发送给 GPT-5.6："
    )
    privacy = (
        "Window titles, file paths, email addresses, URLs, and photos are not included."
        if language == "en"
        else "不会包含窗口标题、文件路径、邮箱、网址或照片。"
    )
    return (
        f"{heading}\n\n"
        f"{json.dumps(payload.as_dict(), ensure_ascii=False, indent=2)}\n\n"
        f"{privacy}"
    )


def generate_ai_summary_for_date(
    database: Database,
    date_text: str,
    api_key: str,
    include_notes: bool,
    language: str,
    timeout_seconds: int = 60,
) -> SummaryResult:
    app_usage = database.get_app_usage_by_date(date_text)
    manual_notes = database.get_manual_notes_by_date(date_text)
    payload = build_sanitized_payload(
        date_text,
        app_usage,
        manual_notes,
        include_notes,
    )
    return generate_ai_summary_from_payload(
        payload,
        api_key=api_key,
        language=language,
        timeout_seconds=timeout_seconds,
    )


def generate_ai_summary_from_payload(
    payload: SanitizedSummaryPayload,
    *,
    api_key: str,
    language: str,
    provider: str = "openai",
    local_base_url: str = "",
    local_model: str = "",
    timeout_seconds: int = 60,
) -> SummaryResult:
    """Generate from an already-sanitized payload; safe to call off the UI thread."""
    date_text = payload.date
    language_instruction = (
        "Write in concise, warm English."
        if language == "en"
        else "请使用简洁、温和的简体中文。"
    )
    instructions = (
        "You are Echo's reflective memory companion. Turn sanitized activity totals "
        "and optional user-selected notes into a grounded daily reflection. Never "
        "invent events, emotions, motives, or facts. Clearly distinguish observations "
        "from suggestions. Return Markdown with: a title, a short narrative, three "
        "evidence-backed highlights, two reflection questions, and one gentle next step. "
        f"{language_instruction}"
    )
    if provider == "local":
        markdown = _request_local_chat_completion(
            instructions=instructions,
            payload=payload,
            base_url=local_base_url,
            model=local_model,
            timeout_seconds=timeout_seconds,
        )
        disclosure = (
            "\n\n---\nGenerated by local AI; the reflection data stayed on this device.\n"
            if language == "en"
            else "\n\n---\n由本地 AI 生成；日报数据未离开此设备。\n"
        )
        path = save_summary_file(date_text, markdown.rstrip() + disclosure)
        return SummaryResult(path=path, markdown=markdown.rstrip() + disclosure)
    if provider != "openai":
        raise RuntimeError(f"Unknown AI provider: {provider}")
    body = json.dumps(
        {
            "model": MODEL,
            "instructions": instructions,
            "input": json.dumps(payload.as_dict(), ensure_ascii=False),
            "max_output_tokens": 1400,
        },
        ensure_ascii=False,
    ).encode("utf-8")
    request = urllib.request.Request(
        RESPONSES_URL,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json; charset=utf-8",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            response_data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"OpenAI request failed with status {exc.code}.") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError("OpenAI request could not be completed.") from exc

    markdown = _extract_output_text(response_data)
    if not markdown.strip():
        raise RuntimeError("GPT-5.6 returned an empty summary.")
    disclosure = (
        "\n\n---\nGenerated by GPT-5.6 from sanitized, user-approved data.\n"
        if language == "en"
        else "\n\n---\n由 GPT-5.6 根据用户确认的脱敏数据生成。\n"
    )
    markdown = markdown.rstrip() + disclosure
    path = save_summary_file(date_text, markdown)
    return SummaryResult(path=path, markdown=markdown)


def _request_local_chat_completion(
    *,
    instructions: str,
    payload: SanitizedSummaryPayload,
    base_url: str,
    model: str,
    timeout_seconds: int,
) -> str:
    if not model.strip():
        raise RuntimeError("Choose a local model in Settings before generating a reflection.")
    endpoint = local_chat_completions_url(base_url)
    body = json.dumps(
        {
            "model": model.strip(),
            "messages": [
                {"role": "system", "content": instructions},
                {"role": "user", "content": json.dumps(payload.as_dict(), ensure_ascii=False)},
            ],
            "temperature": 0.2,
        },
        ensure_ascii=False,
    ).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            response_data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Local AI request failed with status {exc.code}.") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError("Local AI could not be reached. Start the local model service and try again.") from exc
    markdown = _extract_chat_completion_text(response_data)
    if not markdown.strip():
        raise RuntimeError("Local AI returned an empty reflection.")
    return markdown


def local_chat_completions_url(base_url: str) -> str:
    normalized = base_url.strip().rstrip("/")
    if not normalized.startswith(("http://", "https://")):
        raise RuntimeError("Local AI server URL must start with http:// or https://")
    return f"{normalized}/chat/completions"


def _extract_output_text(response_data: dict[str, object]) -> str:
    parts: list[str] = []
    for item in response_data.get("output", []):
        if not isinstance(item, dict):
            continue
        for content in item.get("content", []):
            if not isinstance(content, dict):
                continue
            if content.get("type") == "output_text" and isinstance(content.get("text"), str):
                parts.append(content["text"])
    return "\n".join(parts)


def _extract_chat_completion_text(response_data: dict[str, object]) -> str:
    choices = response_data.get("choices", [])
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0]
    if not isinstance(first, dict):
        return ""
    message = first.get("message", {})
    return message.get("content", "") if isinstance(message, dict) and isinstance(message.get("content"), str) else ""
