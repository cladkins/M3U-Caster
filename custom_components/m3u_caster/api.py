"""Xtream / REST client for M3U Caster."""
from __future__ import annotations

import base64
import logging
from datetime import datetime, timezone
from typing import Any

import aiohttp

_LOGGER = logging.getLogger(__name__)
TIMEOUT = aiohttp.ClientTimeout(total=30)


class M3UCasterAuthError(Exception):
    """Bad credentials."""


class M3UCasterAPI:
    def __init__(self, session: aiohttp.ClientSession, base_url: str, username: str, password: str, api_token: str | None = None) -> None:
        self._session = session
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.api_token = api_token or ""

    async def _xtream(self, action: str, **params: Any) -> Any:
        query = {"username": self.username, "password": self.password, "action": action, **params}
        async with self._session.get(f"{self.base_url}/player_api.php", params=query, timeout=TIMEOUT) as resp:
            if resp.status in (401, 403):
                raise M3UCasterAuthError("Xtream auth rejected")
            resp.raise_for_status()
            return await resp.json(content_type=None)

    async def _rest(self, path: str, **params: Any) -> Any:
        headers = {"Accept": "application/json"}
        if self.api_token:
            headers["Authorization"] = f"Bearer {self.api_token}"
        async with self._session.get(f"{self.base_url}{path}", params=params, headers=headers, timeout=TIMEOUT) as resp:
            if resp.status in (401, 403):
                raise M3UCasterAuthError("API token rejected")
            resp.raise_for_status()
            return await resp.json(content_type=None)

    async def list_playlists(self) -> list[dict[str, str]]:
        data = await self._rest("/user/playlists")
        if isinstance(data, dict):
            data = data.get("data", [data])
        return [{"name": str(p.get("name")), "uuid": str(p.get("uuid"))} for p in data if isinstance(p, dict) and p.get("uuid")]

    async def get_user_info(self) -> dict[str, Any]:
        data = await self._xtream("get_user_info")
        info = data.get("user_info", data) if isinstance(data, dict) else {}
        if str(info.get("auth", "0")).lower() not in ("1", "true"):
            raise M3UCasterAuthError("auth flag not set")
        return info

    async def get_live_streams(self) -> list[dict[str, Any]]:
        data = await self._xtream("get_live_streams")
        return data if isinstance(data, list) else []

    async def get_live_categories(self) -> dict[str, str]:
        data = await self._xtream("get_live_categories")
        if not isinstance(data, list):
            return {}
        return {str(c.get("category_id")): str(c.get("category_name", "")) for c in data}

    async def get_short_epg(self, stream_id: str, limit: int = 2) -> list[dict[str, Any]]:
        data = await self._xtream("get_short_epg", stream_id=stream_id, limit=limit)
        listings = data.get("epg_listings", []) if isinstance(data, dict) else []
        return [self._parse_programme(p) for p in listings if isinstance(p, dict)]

    async def sync_playlist(self, uuid: str, force: bool = True) -> Any:
        return await self._rest(f"/playlist/{uuid}/sync", force=str(force).lower())

    def stream_url(self, stream_id: str) -> str:
        return f"{self.base_url}/live/{self.username}/{self.password}/{stream_id}.m3u8"

    @staticmethod
    def _b64(value: Any) -> str:
        if not isinstance(value, str) or not value:
            return ""
        try:
            return base64.b64decode(value).decode("utf-8", errors="ignore").strip()
        except Exception:  # noqa: BLE001
            return value

    @staticmethod
    def _ts(value: Any, fallback: Any) -> datetime | None:
        try:
            if value not in (None, "", 0, "0"):
                return datetime.fromtimestamp(int(value), tz=timezone.utc)
        except (TypeError, ValueError):
            pass
        if isinstance(fallback, str) and fallback:
            try:
                return datetime.fromisoformat(fallback.replace(" ", "T")).replace(tzinfo=timezone.utc)
            except ValueError:
                return None
        return None

    def _parse_programme(self, p: dict[str, Any]) -> dict[str, Any]:
        return {
            "title": self._b64(p.get("title")) or "Unknown",
            "description": self._b64(p.get("description")),
            "start": self._ts(p.get("start_timestamp"), p.get("start")),
            "end": self._ts(p.get("stop_timestamp"), p.get("end")),
            "now_playing": str(p.get("now_playing", "0")).lower() in ("1", "true"),
        }
