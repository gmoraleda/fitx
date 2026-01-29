from __future__ import annotations

import datetime as _dt
from typing import Iterable, List

from .models import CourseEvent


def _escape_ics(text: str) -> str:
    s = (
        text.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
    )
    return s


def _fold_line(line: str) -> List[str]:
    # RFC 5545: lines MUST be folded at 75 octets; we approximate 75 chars.
    max_len = 75
    out: List[str] = []
    while len(line) > max_len:
        out.append(line[:max_len])
        line = " " + line[max_len:]
    out.append(line)
    return out


def _vtz_europe_berlin() -> List[str]:
    # Static VTIMEZONE covering recent years; good enough for subscription clients
    return [
        "BEGIN:VTIMEZONE",
        "TZID:Europe/Berlin",
        "X-LIC-LOCATION:Europe/Berlin",
        "BEGIN:DAYLIGHT",
        "TZOFFSETFROM:+0100",
        "TZOFFSETTO:+0200",
        "TZNAME:CEST",
        "DTSTART:19700329T020000",
        "RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=-1SU",
        "END:DAYLIGHT",
        "BEGIN:STANDARD",
        "TZOFFSETFROM:+0200",
        "TZOFFSETTO:+0100",
        "TZNAME:CET",
        "DTSTART:19701025T030000",
        "RRULE:FREQ=YEARLY;BYMONTH=10;BYDAY=-1SU",
        "END:STANDARD",
        "END:VTIMEZONE",
    ]


def _fmt_dt_utc(dt: _dt.datetime) -> str:
    return dt.astimezone(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _fmt_local(dt: _dt.datetime) -> str:
    # No Z; local time with TZID provided on property
    return dt.strftime("%Y%m%dT%H%M%S")


def generate_ics(course_id: int, events: Iterable[CourseEvent]) -> str:
    now = _dt.datetime.now(tz=_dt.timezone.utc)
    lines: List[str] = []
    lines.append("BEGIN:VCALENDAR")
    lines.append("PRODID:-//fitx-local//ics//EN")
    lines.append("VERSION:2.0")
    lines.append("CALSCALE:GREGORIAN")
    lines.append("METHOD:PUBLISH")
    lines.extend(_vtz_europe_berlin())

    sorted_events = sorted(events, key=lambda e: (e.start, e.title))
    for ev in sorted_events:
        lines.append("BEGIN:VEVENT")
        lines.append(f"UID:fitx-{course_id}-{_escape_ics(ev.id)}@local")
        lines.append(f"DTSTAMP:{_fmt_dt_utc(now)}")
        lines.append(f"DTSTART;TZID=Europe/Berlin:{_fmt_local(ev.start)}")
        lines.append(f"DTEND;TZID=Europe/Berlin:{_fmt_local(ev.end)}")
        lines.append(f"SUMMARY:{_escape_ics(ev.title)}")

        desc_parts: List[str] = []
        if ev.instructor:
            desc_parts.append(f"Instructor: {ev.instructor}")
        if ev.room:
            desc_parts.append(f"Room: {ev.room}")
        if ev.description:
            desc_parts.append(ev.description)
        if desc_parts:
            _desc_joined = "\n".join(desc_parts)
            lines.append(f"DESCRIPTION:{_escape_ics(_desc_joined)}")
        if ev.location:
            lines.append(f"LOCATION:{_escape_ics(ev.location)}")
        lines.append("END:VEVENT")

    lines.append("END:VCALENDAR")

    # Fold lines
    folded: List[str] = []
    for ln in lines:
        folded.extend(_fold_line(ln))
    return "\r\n".join(folded) + "\r\n"
