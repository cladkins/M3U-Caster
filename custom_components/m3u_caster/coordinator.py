"""Polls channels and EPG for one playlist."""
from __future__ import annotations

import asyncio
import logging
from collections import Counter
from datetime import datetime, timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import M3UCasterAPI, M3UCasterAuthError
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)
TITLE_MAX = 40


class M3UCasterCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    def __init__(self, hass: HomeAssistant, api: M3UCasterAPI, interval: int, epg_limit: int) -> None:
        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=timedelta(seconds=interval))
        self.api = api
        self.epg_limit = epg_limit

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            streams, categories = await asyncio.gather(self.api.get_live_streams(), self.api.get_live_categories())
        except M3UCasterAuthError as err:
            raise UpdateFailed(f"auth failed: {err}") from err
        except Exception as err:  # noqa: BLE001
            raise UpdateFailed(f"channel fetch failed: {err}") from err

        channels: dict[str, dict[str, Any]] = {}
        for s in streams:
            sid = str(s.get("stream_id", ""))
            if not sid:
                continue
            channels[sid] = {
                "stream_id": sid,
                "name": str(s.get("name", sid)),
                "group": categories.get(str(s.get("category_id")), ""),
                "logo": s.get("stream_icon") or "",
                "tvg_id": s.get("epg_channel_id") or "",
                "url": self.api.stream_url(sid),
                "now": None,
                "next": None,
            }

        sem = asyncio.Semaphore(6)

        async def fetch_epg(sid: str) -> None:
            async with sem:
                try:
                    listings = await self.api.get_short_epg(sid, self.epg_limit)
                except Exception as err:  # noqa: BLE001
                    _LOGGER.debug("EPG fetch failed for %s: %s", sid, err)
                    return
            now_ts = dt_util.utcnow()
            current = upcoming = None
            for p in listings:
                start, end = p.get("start"), p.get("end")
                if current is None and (p.get("now_playing") or (start and end and start <= now_ts <= end)):
                    current = p
                elif start and start > now_ts and upcoming is None:
                    upcoming = p
            if current is None and listings:
                current = listings[0]
                upcoming = listings[1] if len(listings) > 1 else None
            channels[sid]["now"] = current
            channels[sid]["next"] = upcoming

        await asyncio.gather(*(fetch_epg(sid) for sid in channels))

        counts = Counter(c["name"] for c in channels.values())
        for c in channels.values():
            c["label"] = self._label(c, counts[c["name"]] > 1)
        return {"channels": channels, "categories": categories}

    @staticmethod
    def _fmt(ts: datetime | None) -> str:
        return dt_util.as_local(ts).strftime("%-I:%M %p") if ts else ""

    def _label(self, c: dict[str, Any], duplicate: bool) -> str:
        name = c["name"] + (f" [{c['stream_id']}]" if duplicate else "")
        now = c.get("now")
        if not now:
            return name
        title = now["title"]
        if len(title) > TITLE_MAX:
            title = title[: TITLE_MAX - 1] + "…"
        start = self._fmt(now.get("start"))
        return f"{name} · {title}" + (f" · {start}" if start else "")
