from __future__ import annotations

import logging
from typing import Optional, Tuple

import httpx


logger = logging.getLogger(__name__)


SAFARI_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)


def build_headers(cookie: Optional[str]) -> dict[str, str]:
    headers = {
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "User-Agent": SAFARI_UA,
    }
    if cookie:
        # Never log the cookie value. Only indicate presence.
        headers["Cookie"] = cookie
        logger.info("FITX cookie: set")
    else:
        logger.info("FITX cookie: not set")
    return headers


async def fetch_course_page(
    client: httpx.AsyncClient, course_id: int, cookie: Optional[str]
) -> Tuple[bytes, Optional[str]]:
    url = f"https://www.fitx.de/courses/{course_id}"
    headers = build_headers(cookie)
    # Conservative timeouts
    for attempt in range(3):
        try:
            resp = await client.get(url, headers=headers, timeout=httpx.Timeout(15.0, connect=10.0))
            ct = resp.headers.get("content-type")
            return resp.content, ct
        except Exception as e:
            logger.warning("Fetch attempt %s failed: %s", attempt + 1, e)
    raise RuntimeError("Failed to fetch FitX schedule after 3 attempts")

