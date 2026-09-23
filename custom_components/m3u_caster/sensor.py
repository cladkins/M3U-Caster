"""One guide sensor per playlist. The card reads its attributes."""
from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import M3UCasterConfigEntry
from .const import CONF_PLAYLIST_NAME, DATA_NOW_CASTING, DOMAIN
from .coordinator import M3UCasterCoordinator


async def async_setup_entry(hass: HomeAssistant, entry: M3UCasterConfigEntry, add: AddEntitiesCallback) -> None:
    playlist_name = entry.data.get(CONF_PLAYLIST_NAME) or entry.title
    add([
        M3UCasterGuideSensor(entry.runtime_data, entry.entry_id, playlist_name),
        M3UCasterEpgCountSensor(entry.runtime_data, entry.entry_id, playlist_name),
    ])


class M3UCasterGuideSensor(CoordinatorEntity[M3UCasterCoordinator], SensorEntity):
    _attr_has_entity_name = True
    _attr_name = "Guide"
    _attr_icon = "mdi:television-guide"
    _attr_native_unit_of_measurement = "channels"
    # The channel table is live data for the cards, not history: a big playlist blows past the
    # recorder's attribute size limit and would only log a warning on every write.
    _unrecorded_attributes = frozenset({"channels", "now_casting"})

    def __init__(self, coordinator: M3UCasterCoordinator, entry_id: str, playlist_name: str) -> None:
        super().__init__(coordinator)
        self._playlist_name = playlist_name
        self._attr_unique_id = f"{entry_id}_guide"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry_id)}, name=f"M3U Caster {playlist_name}", manufacturer="M3U Caster")

    @property
    def native_value(self) -> int:
        return len((self.coordinator.data or {}).get("channels", {}))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        channels = (self.coordinator.data or {}).get("channels", {})
        rows = []
        for c in channels.values():
            now, nxt = c.get("now") or {}, c.get("next") or {}
            rows.append({
                "stream_id": c["stream_id"], "name": c["name"], "number": c.get("number"), "group": c["group"],
                "logo": c["logo"], "label": c["label"],
                "now": now.get("title"), "now_start": now.get("start"), "now_end": now.get("end"),
                "next": nxt.get("title"), "next_start": nxt.get("start"),
                "programmes": [
                    {"title": p.get("title"), "start": p.get("start"), "end": p.get("end")}
                    for p in (c.get("programmes") or [])
                ],
            })
        casting = {
            player: entry for player, entry in self.hass.data.get(DATA_NOW_CASTING, {}).items()
            if entry.get("stream_id") in channels
        }
        return {"playlist": self._playlist_name, "channels": rows, "now_casting": casting}


class M3UCasterEpgCountSensor(CoordinatorEntity[M3UCasterCoordinator], SensorEntity):
    """How much EPG data the guide is actually holding right now, a health check for the EPG source."""

    _attr_has_entity_name = True
    _attr_name = "EPG Programmes"
    _attr_icon = "mdi:calendar-text"
    _attr_native_unit_of_measurement = "programmes"

    def __init__(self, coordinator: M3UCasterCoordinator, entry_id: str, playlist_name: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry_id}_epg_count"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry_id)}, name=f"M3U Caster {playlist_name}", manufacturer="M3U Caster")

    @property
    def native_value(self) -> int:
        channels = (self.coordinator.data or {}).get("channels", {})
        return sum(len(c.get("programmes") or []) for c in channels.values())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        channels = (self.coordinator.data or {}).get("channels", {})
        return {
            "channels_with_programmes": sum(1 for c in channels.values() if c.get("programmes")),
            "channels_total": len(channels),
            "source": "xmltv" if self.coordinator.epg_url else "per_channel",
        }
