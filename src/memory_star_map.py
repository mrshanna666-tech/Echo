from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import datetime
import hashlib
import math

from src.database.models import AppUsage, ManualNote
from src.utils.time_utils import parse_db_datetime


@dataclass(frozen=True)
class StarSource:
    kind: str
    record_id: int
    date: str
    title: str
    detail: str
    timestamp: str
    duration_seconds: int = 0


@dataclass(frozen=True)
class MemoryStar:
    key: str
    kind: str
    label: str
    app_name: str
    sources: tuple[StarSource, ...]
    position: tuple[float, float]


@dataclass(frozen=True)
class StarLink:
    source: str
    target: str
    kind: str  # app, chronology, or nearby; never a causal inference.


@dataclass(frozen=True)
class MemoryAtlas:
    stars: tuple[MemoryStar, ...] = ()
    links: tuple[StarLink, ...] = ()
    app_count: int = 0
    source_count: int = 0
    day_count: int = 0
    hidden_apps: int = 0
    hidden_days: int = 0
    hidden_notes: int = 0


def _activity_source(row: AppUsage) -> StarSource:
    return StarSource("activity", row.id, row.date, row.app_name, row.window_title,
                      row.start_time, max(row.duration_seconds, 0))


def _gap_to_activity(moment: datetime, row: AppUsage) -> float:
    try:
        start = parse_db_datetime(row.start_time)
        end = max(start, parse_db_datetime(row.end_time)) if row.end_time else start
    except (ValueError, TypeError):
        return math.inf
    return max((start - moment).total_seconds(), (moment - end).total_seconds(), 0)


def _seed(key: str) -> float:
    """A process-independent seed; Python's hash changes between launches."""
    return int.from_bytes(hashlib.blake2b(key.encode("utf-8"), digest_size=8).digest(), "big") / 2**64


def _layout_stars(stars: list[MemoryStar], links: list[StarLink]) -> list[MemoryStar]:
    """Arrange stable, irregular islands without a continuously running solver.

    Geometry expresses the existing application and nearby-note links only.
    Independent notes form their own field, without acquiring any new links.
    """
    if not stars:
        return []
    golden_angle = math.pi * (3 - math.sqrt(5))
    groups = {star.key: [star] for star in stars if star.kind == "app"}
    membership = {link.target: link.source for link in links if link.kind == "app"}
    nearby = {link.source: link.target for link in links if link.kind == "nearby"}
    for note, day in nearby.items():
        membership[note] = membership[day]
    independent: list[MemoryStar] = []
    for star in stars:
        if star.kind != "app":
            if star.key in membership:
                groups[membership[star.key]].append(star)
            else:
                independent.append(star)
    if independent:
        groups["independent"] = independent

    islands: list[tuple[dict[str, list[float]], float, float]] = []
    for group_key, members in groups.items():
        positions: dict[str, list[float]] = {}
        hub_key = members[0].key if members[0].kind == "app" else None
        phase = _seed(group_key) * math.tau
        stretch = 1.08 + _seed(group_key + ":stretch") * 0.23
        tilt = (_seed(group_key + ":tilt") - 0.5) * 0.8
        index = 0
        note_counts: dict[str, int] = defaultdict(int)
        for star in members:
            if star.kind == "app":
                positions[star.key] = [0.0, 0.0]
                continue
            if star.key in nearby:
                target = nearby[star.key]
                offset = note_counts[target]
                note_counts[target] += 1
                angle = _seed(star.key) * math.tau + offset * golden_angle
                radius = 60 + math.sqrt(offset) * 37
                origin = positions[target]
                positions[star.key] = [origin[0] + math.cos(angle) * radius,
                                       origin[1] + math.sin(angle) * radius]
            else:
                angle = phase + index * golden_angle + (_seed(star.key) - 0.5) * 0.7
                radius = (75 if hub_key else 0) + math.sqrt(index + 0.7) * 33
                radius *= 0.90 + _seed(star.key + ":radius") * 0.20
                x, y = math.cos(angle) * radius * stretch, math.sin(angle) * radius * 0.82
                positions[star.key] = [x * math.cos(tilt) - y * math.sin(tilt),
                                       x * math.sin(tilt) + y * math.cos(tilt)]
                index += 1

        # Resolve close targets once when the data changes. Keep the hub fixed;
        # the short local passes also handle many notes attached to one day.
        keys = list(positions)
        for _ in range(80):
            largest_push = 0.0
            for i, first in enumerate(keys):
                for second in keys[i + 1:]:
                    a, b = positions[first], positions[second]
                    dx, dy = b[0] - a[0], b[1] - a[1]
                    distance = math.hypot(dx, dy)
                    minimum = 88.0 if hub_key in (first, second) else 43.0
                    if distance >= minimum:
                        continue
                    if distance < 0.001:
                        angle = _seed(first + second) * math.tau
                        dx, dy, distance = math.cos(angle), math.sin(angle), 1.0
                    push = minimum - distance
                    largest_push = max(largest_push, push)
                    first_share = 0.0 if first == hub_key else (1.0 if second == hub_key else 0.5)
                    a[0] -= dx / distance * push * first_share
                    a[1] -= dy / distance * push * first_share
                    b[0] += dx / distance * push * (1.0 - first_share)
                    b[1] += dy / distance * push * (1.0 - first_share)
            if largest_push < 0.05:
                break
        left = min(point[0] for point in positions.values())
        right = max(point[0] for point in positions.values())
        top = min(point[1] for point in positions.values())
        bottom = max(point[1] for point in positions.values())
        middle = ((left + right) / 2, (top + bottom) / 2)
        for point in positions.values():
            point[0] -= middle[0]
            point[1] -= middle[1]
        islands.append((positions, (right - left) / 2 + 60, (bottom - top) / 2 + 60))

    # Low-discrepancy seeds avoid a ring of identical application hubs. Pack
    # elliptical bounds in a landscape field, leaving breathing room between
    # independent constellations even when one has many more records.
    centers = [[math.cos(i * golden_angle + 0.3) * math.sqrt(i) * 280 * 1.35,
                math.sin(i * golden_angle + 0.3) * math.sqrt(i) * 280 * 0.82]
               for i in range(len(islands))]
    for _ in range(100):
        largest_push = 0.0
        for i, (_, width, height) in enumerate(islands):
            for j in range(i + 1, len(islands)):
                horizontal = width + islands[j][1] + 24
                vertical = height + islands[j][2] + 24
                dx = (centers[j][0] - centers[i][0]) / horizontal
                dy = (centers[j][1] - centers[i][1]) / vertical
                distance = math.hypot(dx, dy)
                if distance >= 1.0:
                    continue
                if distance < 0.001:
                    dx, dy, distance = 1.0, 0.0, 1.0
                push = (1.0 - distance) * 0.5
                largest_push = max(largest_push, push)
                x, y = dx / distance * push * horizontal, dy / distance * push * vertical
                centers[i][0] -= x
                centers[i][1] -= y
                centers[j][0] += x
                centers[j][1] += y
        if largest_push < 0.0001:
            break
    final = {key: (point[0] + center[0], point[1] + center[1])
             for (positions, _, _), center in zip(islands, centers)
             for key, point in positions.items()}
    if len(final) >= 6:
        width = max(point[0] for point in final.values()) - min(point[0] for point in final.values())
        height = max(point[1] for point in final.values()) - min(point[1] for point in final.values())
        # A wide composition uses the full desktop canvas. Only expand an
        # axis, so fitting its shape never undoes the target separation above.
        spread = max(1.0, height * 1.7 / max(width, 1.0))
        final = {key: (point[0] * spread, point[1]) for key, point in final.items()}
    return [replace(star, position=final[star.key]) for star in stars]


def build_memory_atlas(
    usage: list[AppUsage],
    notes: list[ManualNote],
    *,
    query: str = "",
    app_filter: str | None = None,
    notes_only: bool = False,
    max_apps: int = 8,
    days_per_app: int = 12,
    max_notes: int = 40,
) -> MemoryAtlas:
    """Build a bounded, deterministic atlas from explicit local source records.

    App stars aggregate one application's records on one day. Notes connect only
    to the nearest visible activity within 30 minutes on the same day. A window
    title is searchable evidence, not an inferred project or user's intention.
    """
    needle = query.strip().casefold()
    usage = sorted(
        (row for row in usage if not notes_only
         and (app_filter is None or row.app_name.casefold() == app_filter.casefold())
         and (not needle or needle in f"{row.app_name} {row.window_title} {row.date}".casefold())),
        key=lambda row: (row.start_time, row.id),
    )
    notes = sorted(
        (row for row in notes if not needle or needle in f"{row.content} {row.date}".casefold()),
        key=lambda row: (row.created_at, row.id),
    )
    grouped: dict[str, list[AppUsage]] = defaultdict(list)
    for row in usage:
        grouped[row.app_name.casefold()].append(row)
    ranked_apps = sorted(grouped, key=lambda key: (
        -sum(max(row.duration_seconds, 0) for row in grouped[key]), key,
    ))
    visible_apps = ranked_apps[:max(1, max_apps)]
    stars: list[MemoryStar] = []
    links: list[StarLink] = []
    visible_usage: list[AppUsage] = []
    daily_keys: dict[tuple[str, str], str] = {}
    hidden_days = 0
    count = len(visible_apps)
    for app_key in visible_apps:
        rows = grouped[app_key]
        label = rows[-1].app_name or "Unknown"
        hub_key = f"app:{app_key}"
        by_day: dict[str, list[AppUsage]] = defaultdict(list)
        for row in rows:
            by_day[row.date].append(row)
        # Selecting one app exposes the whole chosen period, rather than just
        # the recent daily stars used to keep the overview readable.
        dates = sorted(by_day)[-(90 if app_filter is not None else max(1, days_per_app)):]
        hidden_days += len(by_day) - len(dates)
        sources = tuple(_activity_source(row) for day in dates for row in by_day[day])
        stars.append(MemoryStar(hub_key, "app", label, label, sources, (0.0, 0.0)))
        previous = None
        for day in dates:
            key = f"day:{app_key}:{day}"
            day_sources = tuple(_activity_source(row) for row in by_day[day])
            stars.append(MemoryStar(key, "day", day, label, day_sources, (0.0, 0.0)))
            links.append(StarLink(hub_key, key, "app"))
            if previous:
                links.append(StarLink(previous, key, "chronology"))
            previous = key
            daily_keys[(app_key, day)] = key
            visible_usage.extend(by_day[day])

    by_date: dict[str, list[AppUsage]] = defaultdict(list)
    for row in visible_usage:
        by_date[row.date].append(row)
    note_candidates: list[tuple[ManualNote, AppUsage | None]] = []
    for note in notes:
        nearest = None
        try:
            moment = parse_db_datetime(note.created_at)
            candidates = by_date.get(note.date, [])
            if candidates:
                nearest = min(candidates, key=lambda row: (
                    _gap_to_activity(moment, row), row.start_time, row.id,
                ))
                if _gap_to_activity(moment, nearest) > 30 * 60:
                    nearest = None
        except (ValueError, TypeError):
            pass
        if app_filter is None or nearest is not None:
            note_candidates.append((note, nearest))

    selected_notes = note_candidates[-max(1, max_notes):]
    for note, nearest in selected_notes:
        source = StarSource("note", note.id, note.date, "", note.content, note.created_at)
        key = f"note:{note.id}"
        app_name = ""
        if nearest:
            app_key = nearest.app_name.casefold()
            app_name = nearest.app_name
            links.append(StarLink(key, daily_keys[(app_key, note.date)], "nearby"))
        stars.append(MemoryStar(key, "note", note.content, app_name, (source,), (0.0, 0.0)))

    stars = _layout_stars(stars, links)

    sources = { (source.kind, source.record_id): source
                for star in stars if star.kind != "app" for source in star.sources }
    return MemoryAtlas(
        tuple(stars), tuple(links), count, len(sources),
        len({source.date for source in sources.values()}),
        len(ranked_apps) - count, hidden_days, len(note_candidates) - len(selected_notes),
    )
