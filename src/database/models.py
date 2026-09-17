from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AppUsage:
    id: int
    date: str
    app_name: str
    window_title: str
    start_time: str
    end_time: str | None
    duration_seconds: int
    created_at: str


@dataclass(frozen=True)
class ManualNote:
    id: int
    date: str
    content: str
    created_at: str


@dataclass(frozen=True)
class ConfirmedMemory:
    id: int
    query: str
    content: str
    created_at: str


@dataclass(frozen=True)
class MemoryEvidence:
    kind: str
    record_id: int
    date: str
    title: str
    detail: str
    timestamp: str
