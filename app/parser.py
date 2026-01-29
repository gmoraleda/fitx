from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, List, Optional

from bs4 import BeautifulSoup
from zoneinfo import ZoneInfo

from .models import CourseEvent


logger = logging.getLogger(__name__)


BERLIN = ZoneInfo("Europe/Berlin")


def _parse_epoch(val: Any) -> Optional[datetime]:
    try:
        v = int(val)
        # Heuristic: ms vs s
        if v > 1_000_000_000_000:
            v = v / 1000.0
        return datetime.fromtimestamp(v, tz=timezone.utc).astimezone(BERLIN)
    except Exception:
        return None


def _parse_iso(val: Any) -> Optional[datetime]:
    if not isinstance(val, str):
        return None
    s = val.strip()
    # Try straight ISO 8601
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            return dt.replace(tzinfo=BERLIN)
        return dt.astimezone(BERLIN)
    except Exception:
        pass
    # Try common formats
    for fmt in (
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%d %H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
    ):
        try:
            dt = datetime.strptime(s, fmt)
            if fmt.endswith("%z"):
                return dt.astimezone(BERLIN)
            return dt.replace(tzinfo=BERLIN)
        except Exception:
            continue
    return None


def parse_any_datetime(val: Any) -> Optional[datetime]:
    return _parse_iso(val) or _parse_epoch(val)


EVENT_KEYS = [
    "events",
    "appointments",
    "schedule",
    "courseSchedule",
    "times",
    "sessions",
    "payload",
]


def extract_events_from_json(data: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []

    def walk(obj: Any, path: str = "$") -> None:
        if isinstance(obj, dict):
            # Direct hits on common keys
            for k in EVENT_KEYS:
                if k in obj and isinstance(obj[k], list):
                    logger.debug("Found key '%s' at %s with %d items", k, path, len(obj[k]))
                    for it in obj[k]:
                        if isinstance(it, dict):
                            found.append(it)
            # Continue walking
            for k, v in obj.items():
                walk(v, f"{path}.{k}")
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                walk(v, f"{path}[{i}]")

    walk(data)
    logger.debug("Total candidate events found: %d", len(found))
    return found


def coerce_event(it: dict[str, Any]) -> Optional[CourseEvent]:
    # Title
    title = (
        it.get("title")
        or it.get("name")
        or it.get("courseName")
        or it.get("course")
        or "FitX Course"
    )

    # Start
    start = (
        parse_any_datetime(it.get("start"))
        or parse_any_datetime(it.get("startTime"))
        or parse_any_datetime(it.get("startDate"))
        or parse_any_datetime(it.get("startDateTime"))
        or parse_any_datetime(it.get("begin"))
        or parse_any_datetime(it.get("from"))
        or parse_any_datetime(it.get("date"))
        or parse_any_datetime(it.get("dateStart"))
    )
    if not start:
        return None

    # End
    end = (
        parse_any_datetime(it.get("end"))
        or parse_any_datetime(it.get("endTime"))
        or parse_any_datetime(it.get("endDate"))
        or parse_any_datetime(it.get("endDateTime"))
        or parse_any_datetime(it.get("to"))
        or parse_any_datetime(it.get("dateEnd"))
    )
    if not end:
        # try to build from duration
        dur_min = None
        for dk in ("durationMinutes", "duration", "length", "minutes"):
            v = it.get(dk)
            if v is not None:
                try:
                    dur_min = int(v)
                    break
                except Exception:
                    pass
        if dur_min:
            end = start + timedelta(minutes=dur_min)
        else:
            # fallback 60 minutes
            end = start + timedelta(minutes=60)

    # Id
    cid = (
        it.get("id")
        or it.get("eventId")
        or it.get("uid")
        or f"{title}-{int(start.timestamp())}"
    )
    cid = str(cid)

    # Optional fields
    location = (
        _coerce_str(it.get("location"))
        or _coerce_str(it.get("place"))
        or _coerce_str(it.get("studio"))
        or None
    )
    instructor = (
        _coerce_str(it.get("instructor"))
        or _coerce_str(it.get("trainer"))
        or _coerce_str(it.get("coach"))
        or None
    )
    room = _coerce_str(it.get("room")) or _coerce_str(it.get("hall")) or None
    description = (
        _coerce_str(it.get("description"))
        or _coerce_str(it.get("details"))
        or None
    )

    return CourseEvent(
        id=cid,
        title=str(title),
        start=start,
        end=end,
        location=location,
        instructor=instructor,
        room=room,
        description=description,
    )


def _coerce_str(v: Any) -> Optional[str]:
    if v is None:
        return None
    if isinstance(v, str):
        return v
    try:
        return str(v)
    except Exception:
        return None


def parse_schedule(data: bytes, content_type: Optional[str]) -> List[CourseEvent]:
    # 1) If content-type is JSON or data looks like JSON, parse directly
    ct = (content_type or "").lower()
    text = None
    if "application/json" in ct or (data[:1] in (b"{", b"[")):
        try:
            obj = json.loads(data.decode("utf-8", errors="replace"))
            return _build_events_from_obj(obj)
        except Exception as e:
            logger.debug("Direct JSON parse failed: %s", e)

    # 2) Otherwise, treat as HTML with embedded JSON
    try:
        text = data.decode("utf-8", errors="replace")
    except Exception:
        text = None
    if not text:
        raise ValueError("Response is not decodable as UTF-8 text")

    soup = BeautifulSoup(text, "html.parser")

    # Try <script type="application/ld+json"> first
    for sc in soup.find_all("script"):
        t = (sc.get("type") or "").lower()
        if "json" in t:
            content = sc.string or sc.text or ""
            content = content.strip()
            if not content:
                continue
            try:
                obj = json.loads(content)
                events = _build_events_from_obj(obj)
                if events:
                    return events
            except Exception:
                continue

    # Fallback: scan all script tags for JSON-like blocks
    scripts = [sc.string or sc.text or "" for sc in soup.find_all("script")]
    candidates: list[str] = []
    for s in scripts:
        s = s.strip()
        if not s:
            continue
        # Heuristic: extract big JSON arrays/objects
        for m in re.finditer(r"(\{.*?\}|\[.*?\])", s, re.DOTALL):
            chunk = m.group(1)
            # Filter too small
            if len(chunk) < 10:
                continue
            candidates.append(chunk)

    # Try larger candidates first
    candidates.sort(key=len, reverse=True)
    for c in candidates[:50]:
        try:
            obj = json.loads(c)
            events = _build_events_from_obj(obj)
            if events:
                return events
        except Exception:
            continue

    raise ValueError("Unable to parse schedule from response (no events found)")


def _build_events_from_obj(obj: Any) -> List[CourseEvent]:
    candidates = extract_events_from_json(obj)
    events: list[CourseEvent] = []
    for it in candidates:
        ev = coerce_event(it)
        if ev:
            events.append(ev)
    # Deduplicate by (id,start,end)
    uniq = {}
    for e in events:
        key = (e.id, int(e.start.timestamp()), int(e.end.timestamp()))
        uniq[key] = e
    events = sorted(uniq.values(), key=lambda e: (e.start, e.title))
    logger.debug("Parsed %d events after normalization", len(events))
    return events
