"""Push a stream set to the QuadStream dashboard (quadstream.tv)."""
from __future__ import annotations

import json
import re

import aiohttp

BASE = "https://quadstream.tv"
SLOTS = 4
TIMEOUT = aiohttp.ClientTimeout(total=30)
_CSRF = re.compile(r'<meta name="csrf-token" content="([^"]+)"')


class QuadStreamError(Exception):
    """Login or update rejected."""


async def _headers(session: aiohttp.ClientSession) -> dict[str, str]:
    """Fetch the dashboard page for its CSRF token; the PHP session cookie lands in the jar."""
    async with session.get(f"{BASE}/stream/", timeout=TIMEOUT) as resp:
        resp.raise_for_status()
        match = _CSRF.search(await resp.text())
    if not match:
        raise QuadStreamError("no CSRF token on the dashboard page")
    # The dashboard's jQuery posts a raw JSON string under the form-urlencoded default type.
    return {"X-CSRF-Token": match.group(1), "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"}


async def async_login(session: aiohttp.ClientSession, username: str, secret: str) -> tuple[str, dict[str, str]]:
    """Log in to a private stream set. Returns its short id and the headers for follow-up calls."""
    headers = await _headers(session)
    body = json.dumps({"username": username, "secret": secret})
    async with session.post(f"{BASE}/stream/api/login", data=body, headers=headers, timeout=TIMEOUT) as resp:
        if resp.status >= 400:
            raise QuadStreamError(f"QuadStream login rejected ({resp.status})")
        short_id = str((await resp.json(content_type=None)).get("short_id") or "")
    if not short_id:
        raise QuadStreamError("QuadStream login returned no stream set id")
    return short_id, headers


async def async_push_streams(session: aiohttp.ClientSession, username: str, secret: str, urls: list[str]) -> str:
    """Write up to four stream URLs into the set's slots (blank the rest) and return the short id."""
    short_id, headers = await async_login(session, username, secret)
    slots = (list(urls) + [""] * SLOTS)[:SLOTS]
    payload = {f"stream{i + 1}": "".join(u.split()) for i, u in enumerate(slots)}
    async with session.post(
        f"{BASE}/stream/api/stream/{short_id}/update", data=json.dumps(payload), headers=headers, timeout=TIMEOUT
    ) as resp:
        if resp.status >= 400:
            raise QuadStreamError(f"QuadStream rejected the update ({resp.status})")
    return short_id
