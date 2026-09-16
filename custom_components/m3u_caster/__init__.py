"""M3U Caster integration."""
from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.loader import async_get_integration

from .api import M3UCasterAPI
from .const import (
    CONF_API_TOKEN, CONF_BASE_URL, CONF_EPG_LIMIT, CONF_PASSWORD, CONF_SCAN_INTERVAL,
    CONF_USERNAME, DEFAULT_EPG_LIMIT, DEFAULT_SCAN_INTERVAL, DOMAIN,
)
from .coordinator import M3UCasterCoordinator
from .services import async_setup_services

_LOGGER = logging.getLogger(__name__)
PLATFORMS: list[Platform] = [Platform.MEDIA_PLAYER, Platform.SENSOR]
FRONTEND_URL = f"/{DOMAIN}/m3u-caster-tv-card.js"
FRONTEND_FILE = Path(__file__).parent / "frontend" / "m3u-caster-tv-card.js"
type M3UCasterConfigEntry = ConfigEntry[M3UCasterCoordinator]


async def _async_register_frontend(hass: HomeAssistant) -> None:
    """Serve the card from the integration and register it as a Lovelace resource."""
    if hass.data.get(f"{DOMAIN}_frontend"):
        return
    hass.data[f"{DOMAIN}_frontend"] = True
    await hass.http.async_register_static_paths(
        [StaticPathConfig(FRONTEND_URL, str(FRONTEND_FILE), cache_headers=False)]
    )
    integration = await async_get_integration(hass, DOMAIN)
    url = f"{FRONTEND_URL}?v={integration.version}"

    lovelace = hass.data.get("lovelace")
    resources = getattr(lovelace, "resources", None) if lovelace is not None else None
    if resources is None and isinstance(lovelace, dict):
        resources = lovelace.get("resources")
    if resources is None:
        _LOGGER.warning("Lovelace resources unavailable (YAML mode?). Add %s as a module resource manually", url)
        return
    if not getattr(resources, "loaded", True):
        await resources.async_load()
        resources.loaded = True
    for item in resources.async_items():
        if str(item.get("url", "")).startswith(FRONTEND_URL):
            if item["url"] != url:
                await resources.async_update_item(item["id"], {"url": url})
            return
    await resources.async_create_item({"res_type": "module", "url": url})


async def async_setup_entry(hass: HomeAssistant, entry: M3UCasterConfigEntry) -> bool:
    await _async_register_frontend(hass)
    api = M3UCasterAPI(
        async_get_clientsession(hass),
        entry.data[CONF_BASE_URL],
        entry.data[CONF_USERNAME],
        entry.data[CONF_PASSWORD],
        entry.data.get(CONF_API_TOKEN),
    )
    coordinator = M3UCasterCoordinator(
        hass, api,
        entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
        entry.options.get(CONF_EPG_LIMIT, DEFAULT_EPG_LIMIT),
    )
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    async_setup_services(hass)
    return True


async def _async_reload(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: M3UCasterConfigEntry) -> bool:
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if ok:
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    return ok
