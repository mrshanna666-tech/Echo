from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from src.config import DATA_DIR
from src.database.db import Database
from src.database.models import AppUsage, ManualNote
from src.utils.time_utils import display_time, today_str


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SummaryResult:
    path: Path
    markdown: str


def generate_today_summary(database: Database) -> SummaryResult | None:
    return generate_summary_for_date(database, today_str())


def generate_summary_for_date(database: Database, date_text: str) -> SummaryResult | None:
    try:
        app_usage = database.get_app_usage_by_date(date_text)
        manual_notes = database.get_manual_notes_by_date(date_text)
        markdown = build_markdown_summary(date_text, app_usage, manual_notes)
        path = save_summary_file(date_text, markdown)
        logger.info("Local summary generated: %s", path)
        return SummaryResult(path=path, markdown=markdown)
    except Exception:
        logger.exception("Local summary generation failed.")
        return None


def get_today_app_usage(database: Database) -> list[AppUsage]:
    try:
        return database.get_app_usage_by_date(today_str())
    except Exception:
        logger.exception("Failed to read today's app usage.")
        return []


def get_today_manual_notes(database: Database) -> list[ManualNote]:
    try:
        return database.get_manual_notes_by_date(today_str())
    except Exception:
        logger.exception("Failed to read today's manual notes.")
        return []


def format_duration(seconds: int | None) -> str:
    if not seconds or seconds <= 0:
        return "不到1分钟"
    minutes = max(seconds // 60, 1)
    hours, remaining_minutes = divmod(minutes, 60)
    if hours and remaining_minutes:
        return f"{hours}小时{remaining_minutes}分钟"
    if hours:
        return f"{hours}小时"
    return f"{remaining_minutes}分钟"


def build_markdown_summary(
    date_text: str,
    app_usage: list[AppUsage],
    manual_notes: list[ManualNote],
) -> str:
    usage_by_app = _usage_by_app(app_usage)
    total_seconds = sum(max(usage.duration_seconds or 0, 0) for usage in app_usage)
    first_time, last_time = _record_time_range(app_usage, manual_notes)
    top_apps = sorted(usage_by_app.items(), key=lambda item: item[1], reverse=True)

    lines = [
        f"# {date_text} Echo 日报",
        "",
        "## 一句话总结",
        "",
        _one_sentence_summary(top_apps, manual_notes),
        "",
        "## 今日概览",
        "",
        f"- 记录时间段：{first_time} - {last_time}" if first_time else "- 记录时间段：今天还没有记录",
        f"- 记录的软件数量：{len(usage_by_app)} 个",
        f"- 手动记录：{len(manual_notes)} 条",
        f"- 总记录时长：{format_duration(total_seconds)}",
        "",
        "## 今天主要使用的软件",
        "",
        "按使用时长从高到低排序：",
        "",
    ]

    if top_apps:
        lines.extend([f"- {app_name}：{format_duration(seconds)}" for app_name, seconds in top_apps])
    else:
        lines.append("今天还没有软件使用记录。")

    lines.extend(
        [
            "",
            "## 今日时间线",
            "",
            "按时间顺序列出主要活动：",
            "",
        ]
    )
    timeline = _timeline_lines(app_usage, manual_notes)
    lines.extend(timeline if timeline else ["今天还没有任何记录。"])

    lines.extend(["", "## 手动记录", ""])
    if manual_notes:
        lines.extend(
            [f"- {_safe_display_time(note.created_at)} {note.content}" for note in manual_notes]
        )
    else:
        lines.append("今天没有手动记录。")

    lines.extend(["", "## 本地规则总结", "", *_rule_summary_lines(top_apps, manual_notes)])
    lines.extend(["", "## 明天可以继续", "", *_tomorrow_suggestions(top_apps, manual_notes)])

    return "\n".join(lines).rstrip() + "\n"


def save_summary_file(date_text: str, markdown: str) -> Path:
    year, month, day = date_text.split("-")
    summary_dir = DATA_DIR / year / month / day
    summary_dir.mkdir(parents=True, exist_ok=True)
    summary_path = summary_dir / "summary.md"
    if summary_path.exists():
        logger.info("summary.md overwritten: %s", summary_path)
    summary_path.write_text(markdown, encoding="utf-8")
    return summary_path


def get_today_summary_path() -> Path:
    year, month, day = today_str().split("-")
    return DATA_DIR / year / month / day / "summary.md"


def _usage_by_app(app_usage: list[AppUsage]) -> dict[str, int]:
    usage_by_app: dict[str, int] = defaultdict(int)
    for usage in app_usage:
        usage_by_app[usage.app_name or "Unknown"] += max(usage.duration_seconds or 0, 0)
    return dict(usage_by_app)


def _record_time_range(
    app_usage: list[AppUsage],
    manual_notes: list[ManualNote],
) -> tuple[str | None, str | None]:
    times: list[str] = []
    for usage in app_usage:
        times.append(usage.start_time)
        if usage.end_time:
            times.append(usage.end_time)
    for note in manual_notes:
        times.append(note.created_at)
    if not times:
        return None, None
    times.sort()
    return _safe_display_time(times[0]), _safe_display_time(times[-1])


def _timeline_lines(app_usage: list[AppUsage], manual_notes: list[ManualNote]) -> list[str]:
    entries = []
    for usage in app_usage:
        entries.append(("app", usage.start_time, usage))
    for note in manual_notes:
        entries.append(("note", note.created_at, note))
    entries.sort(key=lambda item: item[1])

    lines = []
    for kind, _, payload in entries:
        if kind == "app":
            usage = payload
            title = f"：{usage.window_title}" if usage.window_title else ""
            lines.append(
                f"- {_safe_display_time(usage.start_time)} - {_safe_display_time(usage.end_time)}  "
                f"{usage.app_name}{title}"
            )
        else:
            note = payload
            lines.append(f"- {_safe_display_time(note.created_at)}           手动记录：{note.content}")
    return lines


def _one_sentence_summary(top_apps: list[tuple[str, int]], manual_notes: list[ManualNote]) -> str:
    if not top_apps and not manual_notes:
        return "今天还没有足够的本地记录，Echo 正在等待一天慢慢展开。"
    if not top_apps:
        return "今天留下了主动记录，自动活动数据还在积累中。"

    top_app = top_apps[0][0]
    category = _category_for_app(top_app)
    if category == "coding":
        return "今天主要围绕项目开发和代码工作展开。"
    if category == "browsing":
        return "今天主要围绕资料查询和网页浏览展开。"
    if category == "embedded":
        return "今天的主要活动偏向嵌入式开发。"
    if category == "writing":
        return "今天的主要活动偏向文档写作。"
    return "今天主要围绕项目开发、资料查询和日常电脑使用展开。"


def _rule_summary_lines(
    top_apps: list[tuple[str, int]],
    manual_notes: list[ManualNote],
) -> list[str]:
    lines = []
    if top_apps:
        top_app = top_apps[0][0]
        category = _category_for_app(top_app)
        if category == "coding":
            lines.append("- 今天使用代码编辑器较多，主要活动偏向项目开发。")
        elif category == "browsing":
            lines.append("- 今天浏览器使用时间较多，主要活动偏向资料查询和网页浏览。")
        elif category == "embedded":
            lines.append("- 今天嵌入式工具使用较多，主要活动偏向嵌入式开发。")
        elif category == "writing":
            lines.append("- 今天文档工具使用较多，主要活动偏向文档写作。")
        else:
            lines.append("- 今天的软件使用比较分散，适合从时间线里回看具体节奏。")
    else:
        lines.append("- 今天还没有软件使用记录，暂时无法判断主要活动方向。")

    if manual_notes:
        lines.append("- 今天留下了主动记录，这些内容可能比自动记录更值得未来回看。")
    else:
        lines.append("- 今天没有手动记录，自动记录只能说明做了什么，还不能说明为什么。")
    return lines


def _tomorrow_suggestions(
    top_apps: list[tuple[str, int]],
    manual_notes: list[ManualNote],
) -> list[str]:
    suggestions = []
    categories = {_category_for_app(app_name) for app_name, _ in top_apps[:3]}
    if "coding" in categories:
        suggestions.append("- 可以继续完善 Echo Recorder 的核心功能。")
    if "browsing" in categories:
        suggestions.append("- 可以把今天查到的资料整理成笔记。")
    if "embedded" in categories:
        suggestions.append("- 可以继续推进嵌入式项目，并记录关键调试结论。")
    if "writing" in categories:
        suggestions.append("- 可以继续整理文档，把今天的材料沉淀下来。")
    if not manual_notes:
        suggestions.append("- 明天可以尝试留下一句真正想对未来自己说的话。")
    if not suggestions:
        suggestions.append("- 可以先保持记录，让 Echo 多积累一些真实的一天。")
    return suggestions[:3]


def _category_for_app(app_name: str) -> str:
    name = app_name.lower()
    if any(key in name for key in ["code", "vscode", "visual studio"]):
        return "coding"
    if any(key in name for key in ["chrome", "edge", "firefox", "browser"]):
        return "browsing"
    if any(key in name for key in ["keil", "stm32", "cubemx"]):
        return "embedded"
    if any(key in name for key in ["word", "wps", "typora", "notepad"]):
        return "writing"
    return "general"


def _safe_display_time(value: str | None) -> str:
    try:
        return display_time(value)
    except Exception:
        logger.exception("Failed to format time value: %s", value)
        return "--:--"
