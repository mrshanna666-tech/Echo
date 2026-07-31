from __future__ import annotations

import re
from dataclasses import dataclass

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.database.db import Database
from src.database.models import AppUsage, ManualNote, MemoryEvidence
from src.i18n import tr
from src.utils.time_utils import display_time, human_duration, now, to_db_datetime, today_str


@dataclass(frozen=True)
class LocalAnswer:
    summary: str
    evidence: tuple[str, ...]
    found: bool
    records: tuple[MemoryEvidence, ...] = ()


def answer_from_local_records(
    query: str, usage: list[AppUsage], notes: list[ManualNote]
) -> LocalAnswer:
    """Return an evidence-only answer; this deliberately makes no AI inference."""
    clean_query = query.strip().lower()
    if not clean_query:
        return LocalAnswer(
            tr("问一个关于过去的问题，我会从本机活动和笔记中找线索。", "Ask about the past and Echo will look through local activity and notes."),
            (),
            False,
        )

    query_terms = re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]{2,}", clean_query)
    asks_for_today = "今天" in clean_query or "today" in clean_query

    def matches(item_text: str, primary_name: str = "") -> bool:
        searchable = item_text.lower()
        return (
            clean_query in searchable
            or (primary_name and primary_name.lower() in clean_query)
            or (asks_for_today and today_str() in searchable)
            or any(term in searchable for term in query_terms if len(term) >= 2)
        )

    matching_usage = [
        item for item in usage
        if matches(f"{item.app_name} {item.window_title} {item.date}", item.app_name)
    ]
    matching_notes = [
        item for item in notes
        if matches(f"{item.date} {item.content}")
    ]
    evidence: list[str] = []
    if matching_usage:
        item = matching_usage[-1]
        evidence.append(
            tr(
                f"活动 · {item.date} {display_time(item.start_time)} · {item.app_name} · {human_duration(item.duration_seconds)}",
                f"Activity · {item.date} {display_time(item.start_time)} · {item.app_name} · {human_duration(item.duration_seconds)}",
            )
        )
    if matching_notes:
        item = matching_notes[-1]
        excerpt = item.content.strip().replace("\n", " ")[:88]
        evidence.append(tr(f"笔记 · {item.date} · {excerpt}", f"Note · {item.date} · {excerpt}"))
    if evidence:
        return LocalAnswer(
            tr(
                f"我找到了 {len(evidence)} 条与“{query.strip()}”直接相关的本地线索。以下是最近的一条；你可以继续用更具体的应用名、项目名或日期追问。",
                f"I found {len(evidence)} local clue(s) directly matching “{query.strip()}”. Here is the most recent one; try an app, project, or date to narrow it down.",
            ),
            tuple(evidence),
            True,
        )
    return LocalAnswer(
        tr(
            "没有找到能直接支撑这个问题的本地线索。试试应用名称、窗口标题、笔记中的词，或具体日期。",
            "No local evidence directly supports that question. Try an app name, window title, words from a note, or a date.",
        ),
        (),
        False,
    )


def answer_from_evidence(query: str, records: list[MemoryEvidence]) -> LocalAnswer:
    """Turn ranked local search results into a concise, source-linked answer."""
    clean_query = query.strip()
    if not clean_query:
        return LocalAnswer(
            tr("问一个关于过去的问题，我会给出可检查的本地证据。", "Ask about the past and Echo will return inspectable local evidence."),
            (),
            False,
        )
    if not records:
        return LocalAnswer(
            tr(
                "没有找到能直接支持这个问题的本地证据。可以换成应用名、项目名、日期或笔记中的词。",
                "No local evidence directly supports that question. Try an app, project, date, or words from a note.",
            ),
            (),
            False,
        )

    labels = {"activity": tr("活动", "Activity"), "note": tr("笔记", "Note"), "confirmed": tr("已确认", "Confirmed")}
    evidence: list[str] = []
    for item in records[:6]:
        excerpt = " ".join((item.detail or "").split())[:120]
        when = display_time(item.timestamp) if len(item.timestamp) >= 19 else ""
        parts = [labels.get(item.kind, item.kind), item.date]
        if when:
            parts.append(when)
        parts.append(item.title)
        if excerpt:
            parts.append(excerpt)
        evidence.append(" · ".join(part for part in parts if part))
    lower_query = clean_query.lower()
    asks_for_apps = any(phrase in lower_query for phrase in ("哪些应用", "什么应用", "哪些软件", "which apps", "what apps"))
    app_names = list(dict.fromkeys(item.title for item in records if item.kind == "activity" and item.title))
    summary = (
        tr(
            f"记录中出现了 {len(app_names)} 个应用：{'、'.join(app_names[:12])}。",
            f"The records contain {len(app_names)} apps: {', '.join(app_names[:12])}.",
        )
        if asks_for_apps and app_names
        else tr(
            f"找到 {len(records)} 条相关本地证据，下面优先展示最相关的 {len(evidence)} 条。回答只基于这些记录，不会补写未记录的事实。",
            f"I found {len(records)} relevant local records and show the {len(evidence)} strongest below. The answer stays grounded in these records.",
        )
    )
    return LocalAnswer(
        summary,
        tuple(evidence),
        True,
        tuple(records[:6]),
    )


class AskEchoPage(QWidget):
    """Evidence-first local search surface for asking Echo about recorded history."""

    timeline_requested = Signal(str, str)

    def __init__(self, database: Database) -> None:
        super().__init__()
        self.database = database
        self._current_answer = LocalAnswer("", (), False)
        self._last_confirmed_memory_id: int | None = None
        self.setObjectName("askEchoPage")
        self.setStyleSheet(
            """
            QWidget#askEchoPage { background: #f7f3ec; }
            QFrame#askComposer, QFrame#askAnswerCard, QFrame#askSideCard {
                background: #fffdfa; border: 1px solid #e8ded1; border-radius: 14px;
            }
            QFrame#askComposer { border-color: #ddd0c0; }
            QLabel#askSubtitle, QLabel#askHint, QLabel#askEvidence, QLabel#askStatus { color: #766d63; }
            QLabel#askPrivacy { color: #3f7559; background: #e9f3eb; border-radius: 12px; padding: 6px 10px; }
            QLabel#askAnswerTitle { color: #3c3026; font-size: 16px; font-weight: 700; }
            QLabel#askAnswerBody { color: #51463b; font-size: 15px; line-height: 1.5; }
            QLabel#askSection { color: #4a3b2e; font-size: 14px; font-weight: 700; }
            QLabel#askEvidence { background: #f8f3eb; border-radius: 8px; padding: 9px 10px; }
            QLabel#askInsight { color: #5a4d40; background: #f7f2eb; border-radius: 9px; padding: 10px; }
            QLineEdit#askInput { background: transparent; border: none; color: #382d24; font-size: 15px; padding: 7px 4px; }
            QPushButton#askButton { background: #6f5039; color: white; border: none; border-radius: 9px; padding: 9px 18px; font-weight: 700; }
            QPushButton#askButton:hover { background: #5b402e; }
            QPushButton#askLink, QPushButton#askSuggestion { background: transparent; color: #805b3d; border: none; text-align: left; padding: 5px 0; }
            QPushButton#askLink:hover, QPushButton#askSuggestion:hover { color: #503725; text-decoration: underline; }
            """
        )
        root = QVBoxLayout(self)
        root.setContentsMargins(34, 28, 34, 34)
        root.setSpacing(18)
        root.setAlignment(Qt.AlignmentFlag.AlignTop)

        header = QHBoxLayout()
        copy = QVBoxLayout()
        copy.setSpacing(4)
        title = QLabel(tr("问 Echo", "Ask Echo"))
        title.setObjectName("pageTitle")
        subtitle = QLabel(tr("询问过去，也让 Echo 更懂你。", "Ask about the past, and help Echo understand you."))
        subtitle.setObjectName("askSubtitle")
        copy.addWidget(title)
        copy.addWidget(subtitle)
        privacy = QLabel(tr("仅本机 · 可解释", "On-device · Explainable"))
        privacy.setObjectName("askPrivacy")
        header.addLayout(copy)
        header.addStretch()
        header.addWidget(privacy)
        root.addLayout(header)

        composer = QFrame()
        composer.setObjectName("askComposer")
        composer_layout = QHBoxLayout(composer)
        composer_layout.setContentsMargins(18, 12, 12, 12)
        self.query_input = QLineEdit()
        self.query_input.setObjectName("askInput")
        self.query_input.setPlaceholderText(tr("问问你的记忆，例如：Echo 是什么时候开始记录的？", "Ask your memory, e.g. when did Echo start recording?"))
        self.ask_button = QPushButton(tr("询问", "Ask"))
        self.ask_button.setObjectName("askButton")
        self.ask_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.ask_button.clicked.connect(self.ask)
        self.query_input.returnPressed.connect(self.ask)
        composer_layout.addWidget(self.query_input, 1)
        composer_layout.addWidget(self.ask_button)
        root.addWidget(composer)

        body = QHBoxLayout()
        body.setSpacing(18)
        answer_card = QFrame()
        answer_card.setObjectName("askAnswerCard")
        answer_layout = QVBoxLayout(answer_card)
        answer_layout.setContentsMargins(22, 20, 22, 20)
        answer_layout.setSpacing(12)
        self.answer_title = QLabel(tr("准备好回顾了吗？", "Ready to look back?"))
        self.answer_title.setObjectName("askAnswerTitle")
        self.answer_body = QLabel()
        self.answer_body.setObjectName("askAnswerBody")
        self.answer_body.setWordWrap(True)
        evidence_heading = QLabel(tr("证据", "Evidence"))
        evidence_heading.setObjectName("askSection")
        self.evidence_box = QVBoxLayout()
        self.evidence_box.setSpacing(8)
        actions = QHBoxLayout()
        self.timeline_button = self._link_button(tr("在时间线查看", "View in Timeline"))
        self.confirm_button = self._link_button(tr("判断正确", "Correct"))
        self.correct_button = self._link_button(tr("纠正 Echo", "Correct Echo"))
        self.undo_button = self._link_button(tr("撤销纠正", "Undo correction"))
        self.undo_button.setVisible(False)
        self.confirm_button.clicked.connect(lambda: self._set_status(tr("这一轮已标记为有帮助；持久化学习会在后续版本开放。", "Marked helpful for this session; persistent learning is coming in a later version.")))
        self.correct_button.clicked.connect(self._correct_echo)
        self.undo_button.clicked.connect(self._undo_correction)
        self.timeline_button.clicked.connect(self._open_in_timeline)
        actions.addWidget(self.timeline_button)
        actions.addWidget(self.confirm_button)
        actions.addWidget(self.correct_button)
        actions.addWidget(self.undo_button)
        actions.addStretch()
        self.status_label = QLabel()
        self.status_label.setObjectName("askStatus")
        self.status_label.setWordWrap(True)
        answer_layout.addWidget(self.answer_title)
        answer_layout.addWidget(self.answer_body)
        answer_layout.addWidget(evidence_heading)
        answer_layout.addLayout(self.evidence_box)
        answer_layout.addLayout(actions)
        answer_layout.addWidget(self.status_label)
        body.addWidget(answer_card, 3)

        side = QVBoxLayout()
        side.setSpacing(18)
        learning = QFrame()
        learning.setObjectName("askSideCard")
        learning_layout = QVBoxLayout(learning)
        learning_layout.setContentsMargins(18, 17, 18, 17)
        learning_layout.setSpacing(10)
        learning_layout.addWidget(self._section_label(tr("Echo 记住了什么", "What Echo has recorded")))
        self.recording_summary = QLabel()
        self.recording_summary.setObjectName("askInsight")
        self.notes_summary = QLabel()
        self.notes_summary.setObjectName("askInsight")
        learning_note = QLabel(tr("推断和偏好尚未自动保存；你始终可以查看并删除本地原始记录。", "Inferences and preferences are not saved automatically; local source records stay inspectable and removable."))
        learning_note.setObjectName("askHint")
        learning_note.setWordWrap(True)
        learning_layout.addWidget(self.recording_summary)
        learning_layout.addWidget(self.notes_summary)
        learning_layout.addWidget(learning_note)
        side.addWidget(learning)
        suggestions = QFrame()
        suggestions.setObjectName("askSideCard")
        suggestions_layout = QVBoxLayout(suggestions)
        suggestions_layout.setContentsMargins(18, 17, 18, 17)
        suggestions_layout.setSpacing(5)
        suggestions_layout.addWidget(self._section_label(tr("试着这样问", "Try asking")))
        for question in [
            tr("我上次用 VS Code 是什么时候？", "When did I last use VS Code?"),
            tr("有没有提到 Echo 的笔记？", "Are there notes that mention Echo?"),
            tr("今天记录了哪些应用？", "Which apps did I record today?"),
        ]:
            button = self._link_button(question)
            button.setObjectName("askSuggestion")
            button.clicked.connect(lambda _checked=False, value=question: self._ask_suggestion(value))
            suggestions_layout.addWidget(button)
        side.addWidget(suggestions)
        side.addStretch()
        body.addLayout(side, 2)
        root.addLayout(body)
        self.refresh()

    def refresh(self) -> None:
        usage = self.database.get_recent_app_usage(limit=5000)
        notes = self.database.search_manual_notes("", limit=1)  # Avoid a full note scan in the idle view.
        self.recording_summary.setText(tr(f"已记录 {len(usage)} 段本地活动", f"{len(usage)} local activity entries recorded"))
        self.notes_summary.setText(tr("活动与笔记只在本机检索", "Activity and notes are searched only on this device"))
        self._show_answer(answer_from_local_records("", usage, notes))

    def ask(self) -> None:
        query = self.query_input.text()
        lower_query = query.lower()
        date_match = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", query)
        date_filter = date_match.group(1) if date_match else None
        if "今天" in query or "today" in lower_query:
            date_filter = today_str()
        asks_for_apps = any(phrase in lower_query for phrase in ("哪些应用", "什么应用", "哪些软件", "which apps", "what apps"))
        search_query = "" if asks_for_apps and date_filter else query
        answer = answer_from_evidence(
            query,
            self.database.search_memory(search_query, limit=100 if asks_for_apps else 20, date=date_filter),
        )
        self._show_answer(answer)

    def _ask_suggestion(self, question: str) -> None:
        self.query_input.setText(question)
        self.ask()

    def _show_answer(self, answer: LocalAnswer) -> None:
        self._current_answer = answer
        self.answer_body.setText(answer.summary)
        self.status_label.clear()
        while self.evidence_box.count():
            item = self.evidence_box.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if answer.evidence:
            for text in answer.evidence:
                evidence = QLabel(text)
                evidence.setObjectName("askEvidence")
                evidence.setWordWrap(True)
                self.evidence_box.addWidget(evidence)
        else:
            empty = QLabel(tr("尚未检索到证据。", "No evidence retrieved yet."))
            empty.setObjectName("askHint")
            self.evidence_box.addWidget(empty)

    def _open_in_timeline(self) -> None:
        first = self._current_answer.records[0] if self._current_answer.records else None
        query = first.title if first else self.query_input.text().strip()
        date = first.date if first else ""
        self.timeline_requested.emit(query, date)

    def _correct_echo(self) -> None:
        correction, accepted = QInputDialog.getMultiLineText(
            self,
            tr("纠正 Echo", "Correct Echo"),
            tr("写下你确认的事实。它会单独保存，不会修改原始记录。", "Write the fact you confirm. It is stored separately and never changes source records."),
        )
        if not accepted or not correction.strip():
            return
        memory_id = self.database.create_confirmed_memory(
            query=self.query_input.text(),
            content=correction,
            created_at=to_db_datetime(now()),
        )
        if memory_id is None:
            self._set_status(tr("纠正未能保存。", "The correction could not be saved."))
            return
        self._last_confirmed_memory_id = memory_id
        self.undo_button.setVisible(True)
        self._set_status(tr("已保存为用户确认记忆，可随时撤销或导出。", "Saved as user-confirmed memory. It can be undone or exported."))

    def _undo_correction(self) -> None:
        if self._last_confirmed_memory_id is None:
            return
        if self.database.delete_confirmed_memory(self._last_confirmed_memory_id):
            self._last_confirmed_memory_id = None
            self.undo_button.setVisible(False)
            self._set_status(tr("刚才的纠正已撤销。", "The last correction was removed."))

    def _set_status(self, message: str) -> None:
        self.status_label.setText(message)

    def _matching_notes(self, query: str) -> list[ManualNote]:
        """Search the whole question and its useful terms without loading all notes."""
        terms = [query.strip()]
        terms.extend(re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]{2,}", query.lower()))
        matches: dict[int, ManualNote] = {}
        for term in terms:
            if len(term.strip()) < 2:
                continue
            for note in self.database.search_manual_notes(term, limit=200):
                matches[note.id] = note
        return sorted(matches.values(), key=lambda item: item.created_at)

    @staticmethod
    def _section_label(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("askSection")
        return label

    @staticmethod
    def _link_button(text: str) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName("askLink")
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        return button
