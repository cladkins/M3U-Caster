"""Polls channels and EPG for one playlist."""
from __future__ import annotations

import asyncio
import logging
from collections import Counter
from datetime import datetime, timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import M3UCasterAPI, M3UCasterAuthError
from .const import DOMAIN
from .epg import parse_xmltv

_LOGGER = logging.getLogger(__name__)
TITLE_MAX = 40
# The guide is one panel request per channel, so it is refreshed incrementally: a channel is re-asked
# only when its current programme is about to end, plus one full pass this often to catch schedule edits.
EPG_FULL_REFRESH = timedelta(hours=6)
EPG_FOLLOWUP_SECS = 5


class M3UCasterCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    def __init__(self, hass: HomeAssistant, api: M3UCasterAPI, interval: int, epg_limit: int, epg_url: str | None = None) -> None:
        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=timedelta(seconds=interval))
        self.api = api
        self.epg_limit = epg_limit
        self.epg_url = epg_url
        self._epg_full_at: datetime | None = None
        self._first_pass = True

    def _epg_stale(self, c: dict[str, Any], now_ts: datetime) -> bool:
        """Ask the panel again once the current programme ends before the next poll."""
        now = c.get("now")
        end = now.get("end") if now else None
        return end is None or end <= now_ts + (self.update_interval or timedelta(minutes=5))

    def _epg_targets(self, channels: dict[str, dict[str, Any]], now_ts: datetime) -> list[str]:
        if self._first_pass:
            # Startup: channels only, so setup is two requests instead of one per channel.
            # The guide fills in on a follow-up refresh a few seconds later.
            self._first_pass = False
            async_call_later(self.hass, EPG_FOLLOWUP_SECS, lambda _: self.hass.async_create_task(self.async_request_refresh()))
            return []
        if self._epg_full_at is None or now_ts - self._epg_full_at >= EPG_FULL_REFRESH:
            self._epg_full_at = now_ts
            return list(channels)
        return [sid for sid, c in channels.items() if self._epg_stale(c, now_ts)]

    async def _apply_xmltv_epg(self, channels: dict[str, dict[str, Any]]) -> None:
        """Fetch and apply a provider's own XMLTV guide, joined to channels by tvg_id (epg_channel_id).

        A fetch or parse failure just leaves now/next unset for this poll; it never fails the
        channel/category fetch that already succeeded above.
        """
        try:
            data = await self.api.get_epg_xml(self.epg_url)
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("EPG XML fetch failed: %s", self._scrub(str(err)))
            return
        by_channel = parse_xmltv(data)
        now_ts = dt_util.utcnow()
        for c in channels.values():
            listings = by_channel.get(c.get("tvg_id") or "")
            if not listings:
                continue
            current = upcoming = None
            for p in listings:
                if current is None and p["end"] and p["start"] <= now_ts <= p["end"]:
                    current = p
                elif p["start"] > now_ts and upcoming is None:
                    upcoming = p
            # Unlike the per-channel lookup, no "closest listing" fallback here: this file can be sparse
            # and stale, and a mismatched programme from hours ago is worse than showing nothing.
            c["now"] = current
            c["next"] = upcoming

    def _scrub(self, text: str) -> str:
        """Keep the playlist credentials out of log lines: aiohttp errors quote the full request URL."""
        for secret in (self.api.password, self.api.username, getattr(self.api, "api_token", None)):
            if secret:
                text = text.replace(str(secret), "***")
        return text

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            streams, categories = await asyncio.gather(self.api.get_live_streams(), self.api.get_live_categories())
        except M3UCasterAuthError as err:
            raise UpdateFailed(f"auth failed: {self._scrub(str(err))}") from err
        except Exception as err:  # noqa: BLE001
            raise UpdateFailed(f"channel fetch failed: {self._scrub(str(err))}") from err

        prev = (self.data or {}).get("channels", {})
        channels: dict[str, dict[str, Any]] = {}
        for s in streams:
            sid = str(s.get("stream_id", ""))
            if not sid:
                continue
            old = prev.get(sid) or {}
            channels[sid] = {
                "stream_id": sid,
                "name": str(s.get("name", sid)),
                "number": s.get("num"),
                "group": categories.get(str(s.get("category_id")), ""),
                "logo": s.get("stream_icon") or "",
                "tvg_id": s.get("epg_channel_id") or "",
                "url": self.api.stream_url(sid),
                "now": old.get("now"),
                "next": old.get("next"),
            }

        if self.epg_url:
            # One request covers the whole guide, so there's no reason to ration it like the per-channel lookup.
            await self._apply_xmltv_epg(channels)
        else:
            targets = self._epg_targets(channels, dt_util.utcnow())
            _LOGGER.debug("guide refresh: %d of %d channels", len(targets), len(channels))
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

            await asyncio.gather(*(fetch_epg(sid) for sid in targets))

        counts = Counter(c["name"] for c in channels.values())
        for c in channels.values():
            # "source" is the stable, EPG-free name a media_player source list can carry
            c["source"] = c["name"] + (f" [{c['stream_id']}]" if counts[c["name"]] > 1 else "")
            c["label"] = self._label(c)
        return {"channels": channels, "categories": categories}

    @staticmethod
    def _fmt(ts: datetime | None) -> str:
        return dt_util.as_local(ts).strftime("%-I:%M %p") if ts else ""

    def _label(self, c: dict[str, Any]) -> str:
        name = c["source"]
        now = c.get("now")
        if not now:
            return name
        title = now["title"]
        if len(title) > TITLE_MAX:
            title = title[: TITLE_MAX - 1] + "…"
        start = self._fmt(now.get("start"))
        return f"{name} · {title}" + (f" · {start}" if start else "")
