"""Cast a channel to a media player and remember what was sent where.

Shared by the services and the media_player platform so both keep the
now-casting bookkeeping that the cards and the guide sensor read.
"""
from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from .const import DATA_NOW_CASTING, DOMAIN
from .player import ROKU_STREAM_TESTER_APP_NAME, async_play_url, async_stop


def coordinators(hass: HomeAssistant) -> list:
    return list(hass.data.get(DOMAIN, {}).values())


def find_channel(hass: HomeAssistant, stream_id: str) -> dict[str, Any] | None:
    for coord in coordinators(hass):
        ch = (coord.data or {}).get("channels", {}).get(stream_id)
        if ch:
            return ch
    return None


def now_casting(hass: HomeAssistant, player: str) -> dict[str, Any] | None:
    return hass.data.get(DATA_NOW_CASTING, {}).get(player)


def set_now_casting(hass: HomeAssistant, player: str, entry: dict[str, Any] | None) -> None:
    casting = hass.data.setdefault(DATA_NOW_CASTING, {})
    if entry is None:
        casting.pop(player, None)
    else:
        casting[player] = entry
    for coord in coordinators(hass):
        coord.async_update_listeners()


async def async_cast_channel(
    hass: HomeAssistant,
    player: str,
    channel: dict[str, Any],
    cast_type: str = "auto",
    app_link: str | None = None,
    auto_confirm: bool = True,
) -> str:
    """Play a channel on a media player and record it. Returns the cast type used."""
    used = await async_play_url(hass, player, channel["url"], channel["name"], cast_type, app_link, auto_confirm)
    set_now_casting(hass, player, {
        "stream_id": channel["stream_id"],
        "app": ROKU_STREAM_TESTER_APP_NAME if used == "roku" else None,
    })
    return used


async def async_stop_cast(hass: HomeAssistant, player: str, cast_type: str = "auto") -> None:
    await async_stop(hass, player, cast_type)
    set_now_casting(hass, player, None)
