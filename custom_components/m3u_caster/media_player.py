"""One channel player per target TV, for remote-first cards.

The Astrion remote renders only RosCard's own card types, and those work off
plain Home Assistant entities: its TV and Media Player cards show a media
player's source list and select from it. So each TV picked in the options gets
a media_player whose sources are the playlist's channels. Selecting a source
casts that channel to the TV through the same path the dashboard card uses;
stop and power run the matching stop path. State mirrors the TV and, while a
cast is showing, the current programme is the media title.
"""
from __future__ import annotations

import logging
import time
from typing import Any

from homeassistant.components.media_player import (
    MediaPlayerDeviceClass, MediaPlayerEntity, MediaPlayerEntityFeature, MediaPlayerState, MediaType,
)
from homeassistant.const import ATTR_ENTITY_ID, STATE_OFF, STATE_STANDBY, STATE_UNAVAILABLE
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, State, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import M3UCasterConfigEntry
from .cast import async_cast_channel, async_stop_cast, now_casting, set_now_casting
from .const import CONF_PLAYLIST_NAME, CONF_REMOTE_GROUPS, CONF_REMOTE_PLAYERS, DOMAIN
from .coordinator import M3UCasterCoordinator

_LOGGER = logging.getLogger(__name__)
# After a cast, the target's integration takes a poll or two to report the new foreground app.
APP_GRACE_SECS = 30
TARGET_OFF = (STATE_OFF, STATE_STANDBY, STATE_UNAVAILABLE)
OWN_FEATURES = MediaPlayerEntityFeature.SELECT_SOURCE | MediaPlayerEntityFeature.STOP | MediaPlayerEntityFeature.TURN_OFF
PASS_THROUGH = (
    MediaPlayerEntityFeature.PLAY | MediaPlayerEntityFeature.PAUSE | MediaPlayerEntityFeature.TURN_ON
    | MediaPlayerEntityFeature.VOLUME_SET | MediaPlayerEntityFeature.VOLUME_MUTE | MediaPlayerEntityFeature.VOLUME_STEP
)


def _target_name(hass: HomeAssistant, entity_id: str) -> str:
    state = hass.states.get(entity_id)
    if state and state.attributes.get("friendly_name"):
        return str(state.attributes["friendly_name"])
    reg_entry = er.async_get(hass).async_get(entity_id)
    if reg_entry and (reg_entry.name or reg_entry.original_name):
        return reg_entry.name or reg_entry.original_name
    return entity_id.split(".", 1)[-1].replace("_", " ").title()


async def async_setup_entry(hass: HomeAssistant, entry: M3UCasterConfigEntry, add: AddEntitiesCallback) -> None:
    targets = [t for t in (entry.options.get(CONF_REMOTE_PLAYERS) or []) if t]
    groups = entry.options.get(CONF_REMOTE_GROUPS) or []
    playlist = entry.data.get(CONF_PLAYLIST_NAME) or entry.title

    # Drop registry entries for targets that were removed from the options.
    reg = er.async_get(hass)
    wanted = {f"{entry.entry_id}_{t}" for t in targets}
    for reg_entry in er.async_entries_for_config_entry(reg, entry.entry_id):
        if reg_entry.domain == "media_player" and reg_entry.unique_id not in wanted:
            reg.async_remove(reg_entry.entity_id)

    add([
        M3UCasterChannelPlayer(entry.runtime_data, entry.entry_id, playlist, target, _target_name(hass, target), groups)
        for target in targets
    ])


class M3UCasterChannelPlayer(CoordinatorEntity[M3UCasterCoordinator], MediaPlayerEntity):
    _attr_has_entity_name = True
    _attr_device_class = MediaPlayerDeviceClass.TV
    _attr_icon = "mdi:television-play"

    def __init__(
        self, coordinator: M3UCasterCoordinator, entry_id: str, playlist: str, target: str, name: str, groups: list[str],
    ) -> None:
        super().__init__(coordinator)
        self._target = target
        self._playlist = playlist
        self._groups = {g for g in groups if g}
        self._attr_name = name
        self._attr_unique_id = f"{entry_id}_{target}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry_id)}, name=f"M3U Caster {playlist}", manufacturer="M3U Caster",
        )
        self._cast: dict[str, Any] | None = None
        self._cast_seen = 0.0

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._sync_cast()
        self.async_on_remove(async_track_state_change_event(self.hass, [self._target], self._target_changed))

    @callback
    def _target_changed(self, event: Event[EventStateChangedData]) -> None:
        new, old = event.data.get("new_state"), event.data.get("old_state")
        went_off = (
            new is not None and new.state in TARGET_OFF
            and (old is None or old.state not in TARGET_OFF)
            and time.monotonic() - self._cast_seen > APP_GRACE_SECS  # a cast may be waking the TV right now
        )
        if went_off and now_casting(self.hass, self._target):
            # The TV went away, so nothing is showing there any more. This pings every listener, us included.
            set_now_casting(self.hass, self._target, None)
            return
        self.async_write_ha_state()

    @callback
    def _handle_coordinator_update(self) -> None:
        self._sync_cast()
        super()._handle_coordinator_update()

    def _sync_cast(self) -> None:
        cur = now_casting(self.hass, self._target)
        if cur is not self._cast:
            self._cast = cur
            self._cast_seen = time.monotonic()

    # --- what the target and the playlist look like right now ---

    @property
    def _target_state(self) -> State | None:
        return self.hass.states.get(self._target)

    def _channels(self) -> dict[str, dict[str, Any]]:
        return (self.coordinator.data or {}).get("channels", {})

    def _sources(self) -> list[dict[str, Any]]:
        return [c for c in self._channels().values() if not self._groups or c["group"] in self._groups]

    def _current(self) -> dict[str, Any] | None:
        """The channel this integration is showing on the target, if the target still looks like it."""
        cast = self._cast
        if not cast:
            return None
        ch = self._channels().get(cast.get("stream_id"))
        target = self._target_state
        if ch is None or target is None or target.state in TARGET_OFF:
            return None
        app, target_app = cast.get("app"), target.attributes.get("app_name")
        if app and target_app and target_app != app and time.monotonic() - self._cast_seen > APP_GRACE_SECS:
            return None
        return ch

    # --- entity surface ---

    @property
    def available(self) -> bool:
        target = self._target_state
        return super().available and target is not None and target.state != STATE_UNAVAILABLE

    @property
    def state(self) -> MediaPlayerState | None:
        target = self._target_state
        if target is None:
            return None
        if target.state in (STATE_OFF, STATE_STANDBY):
            return MediaPlayerState(target.state)
        if self._current() is None:
            return MediaPlayerState.IDLE
        if target.state in (MediaPlayerState.PAUSED, MediaPlayerState.BUFFERING):
            return MediaPlayerState(target.state)
        return MediaPlayerState.PLAYING

    @property
    def supported_features(self) -> MediaPlayerEntityFeature:
        target = self._target_state
        theirs = int(target.attributes.get("supported_features", 0) or 0) if target else 0
        return OWN_FEATURES | (MediaPlayerEntityFeature(theirs) & PASS_THROUGH)

    @property
    def source_list(self) -> list[str]:
        return [c["source"] for c in self._sources()]

    @property
    def source(self) -> str | None:
        ch = self._current()
        return ch["source"] if ch else None

    @property
    def media_content_type(self) -> MediaType | None:
        return MediaType.CHANNEL if self._current() else None

    @property
    def media_content_id(self) -> str | None:
        ch = self._current()
        return ch["stream_id"] if ch else None

    @property
    def media_channel(self) -> str | None:
        ch = self._current()
        return ch["name"] if ch else None

    @property
    def media_title(self) -> str | None:
        ch = self._current()
        if not ch:
            return None
        return (ch.get("now") or {}).get("title") or ch["name"]

    @property
    def media_image_url(self) -> str | None:
        ch = self._current()
        return (ch.get("logo") or None) if ch else None

    @property
    def volume_level(self) -> float | None:
        target = self._target_state
        return target.attributes.get("volume_level") if target else None

    @property
    def is_volume_muted(self) -> bool | None:
        target = self._target_state
        return target.attributes.get("is_volume_muted") if target else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs: dict[str, Any] = {"target": self._target, "playlist": self._playlist}
        ch = self._current()
        if ch:
            now, nxt = ch.get("now") or {}, ch.get("next") or {}
            attrs.update({
                "stream_id": ch["stream_id"], "group": ch["group"],
                "now_start": now.get("start"), "now_end": now.get("end"),
                "next": nxt.get("title"), "next_start": nxt.get("start"),
            })
        return attrs

    # --- commands ---

    async def _forward(self, service: str, **data: Any) -> None:
        await self.hass.services.async_call(
            "media_player", service, {ATTR_ENTITY_ID: self._target, **data}, blocking=True,
        )

    async def async_select_source(self, source: str) -> None:
        wanted = (source or "").strip()
        sources = self._sources()
        match = [c for c in sources if c["source"] == wanted]
        if not match:
            # Accept a bare channel name when it is unambiguous, so scripts need not know the [id] suffix.
            match = [c for c in sources if c["name"] == wanted]
        if len(match) != 1:
            raise ServiceValidationError(f"{source!r} is not a channel in the {self._playlist} playlist")
        await async_cast_channel(self.hass, self._target, match[0])

    async def async_media_stop(self) -> None:
        await async_stop_cast(self.hass, self._target)

    async def async_turn_off(self) -> None:
        # Sleeping the TV ends the stream; sending Select/Home first would only wake it again.
        await self._forward("turn_off")
        set_now_casting(self.hass, self._target, None)

    async def async_turn_on(self) -> None:
        await self._forward("turn_on")

    async def async_media_play(self) -> None:
        await self._forward("media_play")

    async def async_media_pause(self) -> None:
        await self._forward("media_pause")

    async def async_set_volume_level(self, volume: float) -> None:
        await self._forward("volume_set", volume_level=volume)

    async def async_mute_volume(self, mute: bool) -> None:
        await self._forward("volume_mute", is_volume_muted=mute)

    async def async_volume_up(self) -> None:
        await self._forward("volume_up")

    async def async_volume_down(self) -> None:
        await self._forward("volume_down")
