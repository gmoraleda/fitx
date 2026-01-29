from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class CourseEvent:
    id: str
    title: str
    start: datetime  # timezone-aware, Europe/Berlin
    end: datetime    # timezone-aware, Europe/Berlin
    location: Optional[str] = None
    instructor: Optional[str] = None
    room: Optional[str] = None
    description: Optional[str] = None

