"""One guide sensor per playlist. The card reads its attributes."""
from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import M3UEditorConfigEntry
from .const import CONF_PLAYLIST_NAME, DOMAIN
from .coordinator import M3UEditorCoordinator


async def async_setup_entry(hass: HomeAssistant, entry: M3UEditorConfigEntry, add: AddEntitiesCallback) -> None:
    add([M3UEditorGuideSensor(entry.runtime_data, entry.entry_id, entry.data.get(CONF_PLAYLIST_NAME) or entry.title)])


class M3UEditorGuideSensor(CoordinatorEntity[M3UEditorCoordinator], SensorEntity):
    _attr_has_entity_name = True
    _attr_name = "Guide"
    _attr_icon = "mdi:television-guide"
    _attr_native_unit_of_measurement = "channels"

    def __init__(self, coordinator: M3UEditorCoordinator, entry_id: str, playlist_name: str) -> None:
        super().__init__(coordinator)
        self._playlist_name = playlist_name
        self._attr_unique_id = f"{entry_id}_guide"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry_id)}, name=f"M3U Editor {playlist_name}", manufacturer="m3u editor")

    @property
    def native_value(self) -> int:
        return len((self.coordinator.data or {}).get("channels", {}))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        rows = []
        for c in (self.coordinator.data or {}).get("channels", {}).values():
            now, nxt = c.get("now") or {}, c.get("next") or {}
            rows.append({
                "stream_id": c["stream_id"], "name": c["name"], "group": c["group"], "logo": c["logo"],
                "label": c["label"],
                "now": now.get("title"), "now_start": now.get("start"), "now_end": now.get("end"),
                "next": nxt.get("title"), "next_start": nxt.get("start"),
            })
        return {"playlist": self._playlist_name, "channels": rows}
