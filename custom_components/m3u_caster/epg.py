"""Parse an XMLTV guide document into per-channel programme listings.

Some panels don't populate the Xtream get_short_epg lookup at all but do publish a
full XMLTV file, often at a per-account URL the panel hands out separately from the
Xtream login. One fetch of that file covers every channel it knows about, which is
far cheaper than asking get_short_epg once per channel.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from typing import Any


def _parse_xmltv_time(value: str) -> datetime | None:
    """Parse XMLTV's "YYYYMMDDHHMMSS +HHMM" timestamp into an aware UTC datetime."""
    value = (value or "").strip()
    if not value:
        return None
    dt_part, _, tz_part = value.partition(" ")
    try:
        naive = datetime.strptime(dt_part[:14], "%Y%m%d%H%M%S")
    except ValueError:
        return None
    tz = timezone.utc
    if len(tz_part) == 5 and tz_part[0] in "+-":
        sign = 1 if tz_part[0] == "+" else -1
        try:
            tz = timezone(sign * timedelta(hours=int(tz_part[1:3]), minutes=int(tz_part[3:5])))
        except ValueError:
            tz = timezone.utc
    return naive.replace(tzinfo=tz).astimezone(timezone.utc)


def parse_xmltv(data: bytes | str) -> dict[str, list[dict[str, Any]]]:
    """Return {epg_channel_id: [{"title", "description", "start", "end"}, ...]}, each sorted by start."""
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        return {}
    by_channel: dict[str, list[dict[str, Any]]] = {}
    for prog in root.findall("programme"):
        cid = prog.get("channel")
        start = _parse_xmltv_time(prog.get("start", ""))
        if not cid or start is None:
            continue
        title_el = prog.find("title")
        desc_el = prog.find("desc")
        by_channel.setdefault(cid, []).append({
            "title": (title_el.text or "").strip() if title_el is not None and title_el.text else "Unknown",
            "description": (desc_el.text or "").strip() if desc_el is not None and desc_el.text else "",
            "start": start,
            "end": _parse_xmltv_time(prog.get("stop", "")),
        })
    for listings in by_channel.values():
        listings.sort(key=lambda p: p["start"])
    return by_channel
