"""Send a stream to a media player using an explicit or detected cast type."""
from __future__ import annotations

import asyncio
import logging
import xml.etree.ElementTree as ET
from typing import Any
from urllib.parse import quote

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import DEFAULT_APP_LINK

_LOGGER = logging.getLogger(__name__)
ROKU_ECP_PORT = 8060
ROKU_STREAM_TESTER_APP_NAME = "Roku Stream Tester"


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


def _roku_host(hass: HomeAssistant, media_player: str) -> str | None:
    """Look up the IP the roku integration already has on file for this media_player's device."""
    ereg = er.async_get(hass)
    mp = ereg.async_get(media_player)
    if not mp or not mp.device_id:
        return None
    dreg = dr.async_get(hass)
    device = dreg.async_get(mp.device_id)
    if not device:
        return None
    for entry_id in device.config_entries:
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry and entry.domain == "roku":
            return entry.data.get("host")
    return None


async def _async_roku_app_id(session: aiohttp.ClientSession, host: str, name: str) -> str | None:
    """Look up a channel's app id by name via ECP's app list query.

    Ids aren't fixed across devices, so they have to be discovered per-device
    rather than hardcoded.
    """
    async with session.get(f"http://{host}:{ROKU_ECP_PORT}/query/apps") as resp:
        resp.raise_for_status()
        body = await resp.text()
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return None
    for app in root.findall("app"):
        if (app.text or "").strip() == name:
            return app.get("id")
    return None


async def _async_roku_ecp_play(hass: HomeAssistant, entity_id: str, url: str, title: str) -> bool:
    """Deep-link a video into Roku Stream Tester via ECP, bypassing HA's roku integration.

    HA's media_player.play_media (via the rokuecp library) throws on this device/firmware
    even though Roku accepts commands fine, and the direct ECP video-launch endpoints
    (/input, /input/<app_id>) both 404 on current firmware. Roku Stream Tester's own
    /launch/<app_id> deep link (params confirmed from a working third-party app's request
    capture) is the path that actually works.
    """
    host = _roku_host(hass, entity_id)
    if not host:
        _LOGGER.warning("no roku host on file for %s; falling back to media_player.play_media", entity_id)
        return False
    session = async_get_clientsession(hass)
    try:
        app_id = await _async_roku_app_id(session, host, ROKU_STREAM_TESTER_APP_NAME)
        if not app_id:
            _LOGGER.warning("Roku Stream Tester channel not found on %s; falling back to media_player.play_media", host)
            return False
        params = {
            "url": url,
            "fmt": "Auto",
            "live": "true",
            "autoCookie": "false",
            "drmParams": "{}",
            "headers": "{}",
            "metadata": "{}",
            "cookies": "{}",
        }
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        async with session.post(f"http://{host}:{ROKU_ECP_PORT}/launch/{app_id}", params=params, headers=headers) as resp:
            resp.raise_for_status()
    except aiohttp.ClientError as err:
        _LOGGER.warning("Roku ECP call to %s failed (%s); falling back to media_player.play_media", host, err)
        return False
    return True


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
    if cast_type == "roku" and await _async_roku_ecp_play(hass, entity_id, url, title):
        return
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
