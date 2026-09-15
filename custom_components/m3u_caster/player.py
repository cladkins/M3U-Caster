"""Send a stream to a media player using an explicit or detected cast type."""
from __future__ import annotations

import asyncio
import logging
from typing import Any
from urllib.parse import quote

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import DEFAULT_APP_LINK

_LOGGER = logging.getLogger(__name__)


def detect_cast_type(hass: HomeAssistant, entity_id: str) -> str:
    entry = er.async_get(hass).async_get(entity_id)
    platform = entry.platform if entry else ""
    if platform == "apple_tv":
        return "apple_tv_app"  # AirPlay URL playback is refused on current tvOS; app launch is the working path
    return platform if platform in ("roku", "cast") else "generic"


def _remote_for(hass: HomeAssistant, media_player: str) -> str | None:
    """Find the remote.* entity on the same device as the media player."""
    reg = er.async_get(hass)
    mp = reg.async_get(media_player)
    if not mp or not mp.device_id:
        return None
    for ent in er.async_entries_for_device(reg, mp.device_id):
        if ent.domain == "remote":
            return ent.entity_id
    return None


async def async_play_url(
    hass: HomeAssistant,
    entity_id: str,
    url: str,
    title: str,
    cast_type: str = "auto",
    app_link: str | None = None,
    auto_confirm: bool = True,
) -> None:
    if cast_type == "auto":
        cast_type = detect_cast_type(hass, entity_id)
    data: dict[str, Any] = {"entity_id": entity_id, "media_content_id": url}
    if cast_type == "roku":
        data["media_content_type"] = "url"
        data["extra"] = {"format": "hls", "name": title}
    elif cast_type == "apple_tv":
        data["media_content_type"] = "video"
    elif cast_type == "apple_tv_app":
        template = app_link or DEFAULT_APP_LINK
        data["media_content_id"] = template.replace("{url}", quote(url, safe=""))
        data["media_content_type"] = "app"
    elif cast_type == "cast":
        data["media_content_type"] = "application/vnd.apple.mpegurl"
        data["extra"] = {"metadata": {"title": title}}
    else:
        data["media_content_type"] = "video"
    _LOGGER.debug("play_media %s via %s: %s", entity_id, cast_type, data["media_content_id"])
    await hass.services.async_call("media_player", "play_media", data, blocking=True)

    if cast_type == "apple_tv_app" and auto_confirm:
        remote = _remote_for(hass, entity_id)
        if remote:
            await asyncio.sleep(1.2)
            await hass.services.async_call(
                "remote", "send_command", {"entity_id": remote, "command": "select"}, blocking=False
            )
        else:
            _LOGGER.debug("no remote entity found for %s; skipping auto confirm", entity_id)


async def async_stop(hass: HomeAssistant, entity_id: str, cast_type: str = "auto") -> None:
    if cast_type == "auto":
        cast_type = detect_cast_type(hass, entity_id)
    if cast_type in ("apple_tv_app", "roku"):
        remote = _remote_for(hass, entity_id)
        if remote:
            await hass.services.async_call("remote", "send_command", {"entity_id": remote, "command": "home"}, blocking=False)
            return
    await hass.services.async_call("media_player", "media_stop", {"entity_id": entity_id}, blocking=False)
