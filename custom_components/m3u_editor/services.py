"""Services for M3U Editor."""
from __future__ import annotations

import logging

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv

from .const import (
    ATTR_APP_LINK, ATTR_AUTO_CONFIRM, ATTR_CAST_TYPE, ATTR_MEDIA_PLAYER, ATTR_PLAYLIST_UUID, ATTR_STREAM_ID,
    CAST_TYPES, DOMAIN, SERVICE_PLAY_STREAM, SERVICE_REFRESH, SERVICE_STOP, SERVICE_SYNC_PLAYLIST,
)
from .player import async_play_url, async_stop

_LOGGER = logging.getLogger(__name__)


def _coordinators(hass: HomeAssistant):
    return list(hass.data.get(DOMAIN, {}).values())


def async_setup_services(hass: HomeAssistant) -> None:
    if hass.services.has_service(DOMAIN, SERVICE_PLAY_STREAM):
        return

    async def play_stream(call: ServiceCall) -> None:
        sid = str(call.data[ATTR_STREAM_ID])
        player = call.data[ATTR_MEDIA_PLAYER]
        cast_type = call.data.get(ATTR_CAST_TYPE, "auto")
        app_link = call.data.get(ATTR_APP_LINK) or None
        auto_confirm = call.data.get(ATTR_AUTO_CONFIRM, True)
        for coord in _coordinators(hass):
            ch = (coord.data or {}).get("channels", {}).get(sid)
            if ch:
                await async_play_url(hass, player, ch["url"], ch["name"], cast_type, app_link, auto_confirm)
                return
        _LOGGER.warning("stream_id %s not found in any playlist", sid)

    async def stop(call: ServiceCall) -> None:
        await async_stop(hass, call.data[ATTR_MEDIA_PLAYER], call.data.get(ATTR_CAST_TYPE, "auto"))

    async def sync_playlist(call: ServiceCall) -> None:
        for coord in _coordinators(hass):
            await coord.api.sync_playlist(call.data.get(ATTR_PLAYLIST_UUID) or coord.api.password)

    async def refresh(call: ServiceCall) -> None:
        for coord in _coordinators(hass):
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
    hass.services.async_register(DOMAIN, SERVICE_SYNC_PLAYLIST, sync_playlist, schema=vol.Schema({vol.Optional(ATTR_PLAYLIST_UUID): cv.string}))
    hass.services.async_register(DOMAIN, SERVICE_REFRESH, refresh)
