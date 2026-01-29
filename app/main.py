from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
from typing import List, Optional

import httpx
from fastapi import FastAPI, Header, HTTPException, Response

from .fetcher import fetch_course_page
from .ics import generate_ics
from .models import CourseEvent
from .parser import parse_schedule
from .store import ensure_data_dir, load_cache, save_cache


logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("fitx")


FITX_COURSE_ID = int(os.environ.get("FITX_COURSE_ID", "53"))
PORT = int(os.environ.get("PORT", "8787"))
REFRESH_INTERVAL_SECONDS = int(os.environ.get("REFRESH_INTERVAL_SECONDS", "900"))
FITX_COOKIE = os.environ.get("FITX_COOKIE")
REFRESH_TOKEN = os.environ.get("REFRESH_TOKEN")
TZ = os.environ.get("TZ", "Europe/Berlin")

# Comma-separated list of keywords to exclude from event titles (case-insensitive)
_default_excludes = "booty x,xamba,x step,fatburn x"
FITX_EXCLUDE_KEYWORDS = os.environ.get("FITX_EXCLUDE_KEYWORDS", _default_excludes)

def _parse_exclude_keywords(raw: str) -> list[str]:
    items = [s.strip().lower() for s in (raw or "").split(",")]
    return [s for s in items if s]

EXCLUDE_KEYWORDS = _parse_exclude_keywords(FITX_EXCLUDE_KEYWORDS)

try:
    os.environ.setdefault("TZ", TZ)
    import time as _time

    if hasattr(_time, "tzset"):
        _time.tzset()
except Exception:
    pass


app = FastAPI()


# Shared state with concurrency protection
cache_lock = asyncio.Lock()
cache_ics: Optional[str] = None
cache_events: Optional[List[CourseEvent]] = None
client: Optional[httpx.AsyncClient] = None
bg_task: Optional[asyncio.Task] = None


async def _refresh_once() -> None:
    global cache_ics, cache_events
    assert client is not None
    logger.info("Refreshing FitX schedule for course_id=%s", FITX_COURSE_ID)
    try:
        data, content_type = await fetch_course_page(client, FITX_COURSE_ID, FITX_COOKIE)
        events = parse_schedule(data, content_type)
        # Apply title-based filtering (case-insensitive substring match)
        if EXCLUDE_KEYWORDS:
            before = len(events)
            lowered = [(e, e.title.lower()) for e in events]
            events = [e for (e, t) in lowered if not any(k in t for k in EXCLUDE_KEYWORDS)]
            removed = before - len(events)
            if removed:
                logger.info("Filtered %d events by keywords: %s", removed, ", ".join(EXCLUDE_KEYWORDS))
        ics_text = generate_ics(FITX_COURSE_ID, events)
        # Atomically persist and update in-memory
        await _update_cache(events, ics_text)
        logger.info("Refresh successful: %d events", len(events))
    except Exception as e:
        logger.error("Refresh failed: %s", e)


async def _update_cache(events: List[CourseEvent], ics_text: str) -> None:
    global cache_ics, cache_events
    # Save to disk first
    save_cache(events, ics_text)
    # Update memory
    async with cache_lock:
        cache_events = events
        cache_ics = ics_text


async def refresh_loop(stop_event: asyncio.Event) -> None:
    await _refresh_once()
    while not stop_event.is_set():
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=REFRESH_INTERVAL_SECONDS)
        except asyncio.TimeoutError:
            pass
        if stop_event.is_set():
            break
        await _refresh_once()


@app.on_event("startup")
async def on_startup() -> None:
    global client, bg_task, cache_ics, cache_events
    ensure_data_dir()
    client = httpx.AsyncClient(http2=False, headers={})
    # Try to load existing cache
    ics_text, events = load_cache()
    async with cache_lock:
        cache_ics = ics_text
        cache_events = events
    if ics_text:
        logger.info("Loaded cached ICS from disk")
    else:
        logger.info("No cached ICS found at startup")
    # Start background loop
    stop_event = asyncio.Event()

    def _handle_sig(*_args: object) -> None:
        stop_event.set()

    loop = asyncio.get_event_loop()
    try:
        loop.add_signal_handler(signal.SIGTERM, _handle_sig)
        loop.add_signal_handler(signal.SIGINT, _handle_sig)
    except (NotImplementedError, RuntimeError):
        # Signals may not be available or we're not in main thread (e.g., TestClient)
        pass
    bg_task = asyncio.create_task(refresh_loop(stop_event))


@app.on_event("shutdown")
async def on_shutdown() -> None:
    global client, bg_task
    if bg_task:
        bg_task.cancel()
        try:
            await bg_task
        except Exception:
            pass
    if client:
        await client.aclose()


@app.get("/health")
async def health() -> Response:
    return Response(content="OK", media_type="text/plain")


@app.get("/calendar.ics")
async def calendar() -> Response:
    async with cache_lock:
        current_ics = cache_ics
        current_events = cache_events
    if current_ics:
        return Response(content=current_ics, media_type="text/calendar; charset=utf-8")
    # if no cached ICS yet, serve an empty calendar so clients can subscribe
    empty = generate_ics(FITX_COURSE_ID, current_events or [])
    return Response(content=empty, media_type="text/calendar; charset=utf-8")


@app.post("/refresh")
async def refresh(x_refresh_token: Optional[str] = Header(default=None, alias="X-Refresh-Token")) -> dict:
    if REFRESH_TOKEN:
        if not x_refresh_token or x_refresh_token != REFRESH_TOKEN:
            raise HTTPException(status_code=401, detail="Unauthorized")
    await _refresh_once()
    async with cache_lock:
        ev_count = len(cache_events or [])
    return {"status": "ok", "events": ev_count}


# Uvicorn will run via Docker CMD binding to 0.0.0.0 and port from env
