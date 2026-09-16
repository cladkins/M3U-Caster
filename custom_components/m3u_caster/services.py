"""Services for M3U Caster."""
from __future__ import annotations

import logging

import aiohttp
import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .cast import async_cast_channel, async_stop_cast, coordinators, find_channel, set_now_casting
from .const import (
    ATTR_APP_LINK, ATTR_AUTO_CONFIRM, ATTR_CAST_TYPE, ATTR_MEDIA_PLAYER, ATTR_PLAYLIST_UUID, ATTR_STREAM_ID,
    ATTR_STREAM_IDS, CAST_TYPES, CONF_QUADSTREAM_SECRET, CONF_QUADSTREAM_USERNAME, DOMAIN, QUADSTREAM_APP_NAME,
    SERVICE_PLAY_MULTIVIEW, SERVICE_PLAY_STREAM, SERVICE_REFRESH, SERVICE_STOP, SERVICE_SYNC_PLAYLIST,
)
from .player import async_launch_app
from .quadstream import QuadStreamError, async_push_streams

_LOGGER = logging.getLogger(__name__)


def async_setup_services(hass: HomeAssistant) -> None:
    if hass.services.has_service(DOMAIN, SERVICE_PLAY_STREAM):
        return

    async def play_stream(call: ServiceCall) -> None:
        sid = str(call.data[ATTR_STREAM_ID])
        ch = find_channel(hass, sid)
        if ch is None:
            _LOGGER.warning("stream_id %s not found in any playlist", sid)
            return
        await async_cast_channel(
            hass, call.data[ATTR_MEDIA_PLAYER], ch, call.data.get(ATTR_CAST_TYPE, "auto"),
            call.data.get(ATTR_APP_LINK) or None, call.data.get(ATTR_AUTO_CONFIRM, True),
        )

    async def stop(call: ServiceCall) -> None:
        await async_stop_cast(hass, call.data[ATTR_MEDIA_PLAYER], call.data.get(ATTR_CAST_TYPE, "auto"))

    async def play_multiview(call: ServiceCall) -> None:
        urls: list[str] = []
        for sid in call.data[ATTR_STREAM_IDS]:
            sid = str(sid).strip()
            ch = find_channel(hass, sid) if sid else None
            if sid and ch is None:
                _LOGGER.warning("stream_id %s not found in any playlist", sid)
            urls.append(ch["url"] if ch else "")
        if not any(urls):
            raise HomeAssistantError("none of the requested stream ids are in a loaded playlist")
        creds = next(
            ((e.options[CONF_QUADSTREAM_USERNAME], e.options.get(CONF_QUADSTREAM_SECRET, ""))
             for e in hass.config_entries.async_entries(DOMAIN) if e.options.get(CONF_QUADSTREAM_USERNAME)),
            None,
        )
        if creds is None:
            raise HomeAssistantError("QuadStream is not set up: add the username and secret in the integration options")
        try:
            await async_push_streams(async_get_clientsession(hass), creds[0], creds[1], urls)
        except (QuadStreamError, aiohttp.ClientError) as err:
            raise HomeAssistantError(f"QuadStream update failed: {err}") from err
        player = call.data.get(ATTR_MEDIA_PLAYER)
        if player:
            await async_launch_app(hass, player, QUADSTREAM_APP_NAME)
            set_now_casting(hass, player, None)

    async def sync_playlist(call: ServiceCall) -> None:
        for coord in coordinators(hass):
            await coord.api.sync_playlist(call.data.get(ATTR_PLAYLIST_UUID) or coord.api.password)

    async def refresh(call: ServiceCall) -> None:
        for coord in coordinators(hass):
            await coord.async_request_refresh()

    hass.services.async_register(DOMAIN, SERVICE_PLAY_STREAM, play_stream, schema=vol.Schema({
        vol.Required(ATTR_STREAM_ID): cv.string,
        vol.Required(ATTR_MEDIA_PLAYER): cv.entity_id,
        vol.Optional(ATTR_CAST_TYPE, default="auto"): vol.In(CAST_TYPES),
        vol.Optional(ATTR_APP_LINK): cv.string,
        vol.Optional(ATTR_AUTO_CONFIRM, default=True): cv.boolean,
    }))
    hass.services.async_register(DOMAIN, SERVICE_STOP, stop, schema=vol.Schema({
        vol.Required(ATTR_MEDIA_PLAYER): cv.entity_id,
        vol.Optional(ATTR_CAST_TYPE, default="auto"): vol.In(CAST_TYPES),
    }))
    hass.services.async_register(DOMAIN, SERVICE_PLAY_MULTIVIEW, play_multiview, schema=vol.Schema({
        vol.Required(ATTR_STREAM_IDS): vol.All(cv.ensure_list, [cv.string], vol.Length(min=1, max=4)),
        vol.Optional(ATTR_MEDIA_PLAYER): cv.entity_id,
    }))
    hass.services.async_register(DOMAIN, SERVICE_SYNC_PLAYLIST, sync_playlist, schema=vol.Schema({vol.Optional(ATTR_PLAYLIST_UUID): cv.string}))
    hass.services.async_register(DOMAIN, SERVICE_REFRESH, refresh)
