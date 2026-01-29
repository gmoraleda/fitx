from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, List

from .models import CourseEvent


DATA_DIR = Path(os.environ.get("DATA_DIR", "/data")).resolve()
CACHE_ICS = DATA_DIR / "cache.ics"
CACHE_JSON = DATA_DIR / "cache.json"


def ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def atomic_write(path: Path, data: bytes) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def save_cache(events: List[CourseEvent], ics_text: str) -> None:
    ensure_data_dir()
    # Save JSON (normalized parsed events)
    json_payload: list[dict[str, Any]] = []
    for e in events:
        json_payload.append(
            {
                "id": e.id,
                "title": e.title,
                "start": e.start.isoformat(),
                "end": e.end.isoformat(),
                "location": e.location,
                "instructor": e.instructor,
                "room": e.room,
                "description": e.description,
            }
        )
    atomic_write(CACHE_JSON, json.dumps(json_payload, ensure_ascii=False, indent=2).encode("utf-8"))
    # Save ICS
    atomic_write(CACHE_ICS, ics_text.encode("utf-8"))


def load_cache() -> tuple[str | None, list[CourseEvent] | None]:
    ics_text: str | None = None
    events: list[CourseEvent] | None = None
    if CACHE_ICS.exists():
        try:
            ics_text = CACHE_ICS.read_text(encoding="utf-8")
        except Exception:
            ics_text = None
    if CACHE_JSON.exists():
        try:
            raw = json.loads(CACHE_JSON.read_text(encoding="utf-8"))
            from datetime import datetime
            from zoneinfo import ZoneInfo

            tz = ZoneInfo("Europe/Berlin")
            events = []
            for it in raw:
                events.append(
                    CourseEvent(
                        id=str(it.get("id", "")),
                        title=str(it.get("title", "")),
                        start=datetime.fromisoformat(it["start"]).astimezone(tz),
                        end=datetime.fromisoformat(it["end"]).astimezone(tz),
                        location=it.get("location"),
                        instructor=it.get("instructor"),
                        room=it.get("room"),
                        description=it.get("description"),
                    )
                )
        except Exception:
            events = None
    return ics_text, events

