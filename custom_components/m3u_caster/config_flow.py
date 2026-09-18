"""Config flow: standard Xtream login (URL, username, password). Optional token enables a playlist picker."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import M3UCasterAPI, M3UCasterAuthError
from .const import (
    CONF_API_TOKEN, CONF_BASE_URL, CONF_EPG_LIMIT, CONF_EPG_URL, CONF_PASSWORD, CONF_PLAYLIST, CONF_PLAYLIST_NAME,
    CONF_QUADSTREAM_SECRET, CONF_QUADSTREAM_USERNAME, CONF_REMOTE_GROUPS, CONF_REMOTE_PLAYERS, CONF_SCAN_INTERVAL,
    CONF_USERNAME, DEFAULT_BASE_URL, DEFAULT_EPG_LIMIT, DEFAULT_SCAN_INTERVAL, DEFAULT_USERNAME, DOMAIN,
)
from .quadstream import QuadStreamError, async_login

_LOGGER = logging.getLogger(__name__)


def _login_schema(cur: dict[str, Any] | None = None) -> vol.Schema:
    cur = cur or {}
    return vol.Schema({
        vol.Required(CONF_BASE_URL, default=cur.get(CONF_BASE_URL, DEFAULT_BASE_URL)): str,
        vol.Required(CONF_USERNAME, default=cur.get(CONF_USERNAME, DEFAULT_USERNAME)): str,
        vol.Optional(CONF_PASSWORD, default=cur.get(CONF_PASSWORD, "")): selector.TextSelector(
            selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)),
        vol.Optional(CONF_PLAYLIST_NAME, default=cur.get(CONF_PLAYLIST_NAME, "")): str,
        vol.Optional(CONF_API_TOKEN, default=cur.get(CONF_API_TOKEN, "")): selector.TextSelector(
            selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)),
    })


def _options_schema(cur: dict[str, Any], groups: list[str], own_players: list[str]) -> vol.Schema:
    return vol.Schema({
        vol.Required(CONF_SCAN_INTERVAL, default=cur.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)):
            selector.NumberSelector(selector.NumberSelectorConfig(min=60, max=3600, step=30, unit_of_measurement="s")),
        vol.Required(CONF_EPG_LIMIT, default=cur.get(CONF_EPG_LIMIT, DEFAULT_EPG_LIMIT)):
            selector.NumberSelector(selector.NumberSelectorConfig(min=1, max=10, step=1)),
        vol.Optional(CONF_EPG_URL, default=cur.get(CONF_EPG_URL, "")): selector.TextSelector(
            selector.TextSelectorConfig(type=selector.TextSelectorType.URL)),
        vol.Optional(CONF_REMOTE_PLAYERS, default=cur.get(CONF_REMOTE_PLAYERS, [])): selector.EntitySelector(
            selector.EntitySelectorConfig(domain="media_player", multiple=True, exclude_entities=own_players)),
        vol.Optional(CONF_REMOTE_GROUPS, default=cur.get(CONF_REMOTE_GROUPS, [])): selector.SelectSelector(
            selector.SelectSelectorConfig(options=groups, multiple=True, custom_value=True,
                                          mode=selector.SelectSelectorMode.DROPDOWN)),
        vol.Optional(CONF_QUADSTREAM_USERNAME, default=cur.get(CONF_QUADSTREAM_USERNAME, "")): str,
        vol.Optional(CONF_QUADSTREAM_SECRET, default=cur.get(CONF_QUADSTREAM_SECRET, "")): selector.TextSelector(
            selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)),
    })


class M3UCasterConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._login: dict[str, Any] = {}
        self._playlists: list[dict[str, str]] = []

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            self._login = user_input
            password = (user_input.get(CONF_PASSWORD) or "").strip()
            token = (user_input.get(CONF_API_TOKEN) or "").strip() or None
            if password:
                result = await self._try_finish(password, user_input.get(CONF_PLAYLIST_NAME) or "")
                if result is not None:
                    return result
                errors["base"] = self._last_error
            elif token:
                api = M3UCasterAPI(async_get_clientsession(self.hass), user_input[CONF_BASE_URL], user_input[CONF_USERNAME], "", token)
                try:
                    self._playlists = await api.list_playlists()
                except M3UCasterAuthError:
                    errors["base"] = "invalid_token"
                except Exception:  # noqa: BLE001
                    _LOGGER.exception("playlist listing failed")
                    errors["base"] = "cannot_connect"
                else:
                    if self._playlists:
                        return await self.async_step_playlist()
                    errors["base"] = "no_playlists"
            else:
                errors["base"] = "password_or_token"
        return self.async_show_form(step_id="user", data_schema=_login_schema(user_input), errors=errors)

    async def async_step_playlist(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            uuid = user_input[CONF_PLAYLIST]
            name = next((p["name"] for p in self._playlists if p["uuid"] == uuid), uuid)
            result = await self._try_finish(uuid, name)
            if result is not None:
                return result
            errors["base"] = self._last_error
        opts = [selector.SelectOptionDict(value=p["uuid"], label=p["name"]) for p in self._playlists]
        schema = vol.Schema({vol.Required(CONF_PLAYLIST): selector.SelectSelector(
            selector.SelectSelectorConfig(options=opts, mode=selector.SelectSelectorMode.DROPDOWN))})
        return self.async_show_form(step_id="playlist", data_schema=schema, errors=errors)

    async def _try_finish(self, password: str, name: str) -> ConfigFlowResult | None:
        """Validate Xtream creds and create the entry. Returns None on failure and sets _last_error."""
        self._last_error = ""
        api = M3UCasterAPI(
            async_get_clientsession(self.hass), self._login[CONF_BASE_URL], self._login[CONF_USERNAME],
            password, (self._login.get(CONF_API_TOKEN) or "").strip() or None,
        )
        try:
            await api.get_user_info()
        except M3UCasterAuthError:
            self._last_error = "invalid_auth"
            return None
        except Exception:  # noqa: BLE001
            _LOGGER.exception("connection test failed")
            self._last_error = "cannot_connect"
            return None
        await self.async_set_unique_id(f"{self._login[CONF_BASE_URL]}::{password}")
        self._abort_if_unique_id_configured()
        title = name or f"{self._login[CONF_USERNAME]}@{self._login[CONF_BASE_URL].split('//')[-1]}"
        data = {
            CONF_BASE_URL: self._login[CONF_BASE_URL],
            CONF_USERNAME: self._login[CONF_USERNAME],
            CONF_PASSWORD: password,
            CONF_API_TOKEN: (self._login.get(CONF_API_TOKEN) or "").strip(),
            CONF_PLAYLIST_NAME: title,
        }
        return self.async_create_entry(title=title, data=data, options={CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL, CONF_EPG_LIMIT: DEFAULT_EPG_LIMIT})

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return M3UCasterOptionsFlow()


class M3UCasterOptionsFlow(OptionsFlow):
    def _channel_groups(self, selected: list[str]) -> list[str]:
        """Category names from the last poll, plus anything already chosen, for the group picker."""
        coordinator = getattr(self.config_entry, "runtime_data", None)
        data = getattr(coordinator, "data", None) or {}
        names = {str(g) for g in (data.get("categories") or {}).values() if g}
        names.update(g for g in selected if g)
        return sorted(names, key=str.casefold)

    def _own_players(self) -> list[str]:
        """This entry's own media_players, kept out of the target picker so a player cannot target itself."""
        reg = er.async_get(self.hass)
        return [
            e.entity_id for e in er.async_entries_for_config_entry(reg, self.config_entry.entry_id)
            if e.domain == "media_player"
        ]

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            user_input[CONF_SCAN_INTERVAL] = int(user_input[CONF_SCAN_INTERVAL])
            user_input[CONF_EPG_LIMIT] = int(user_input[CONF_EPG_LIMIT])
            user_input[CONF_EPG_URL] = (user_input.get(CONF_EPG_URL) or "").strip()
            user_input[CONF_REMOTE_PLAYERS] = [p for p in (user_input.get(CONF_REMOTE_PLAYERS) or []) if p]
            user_input[CONF_REMOTE_GROUPS] = [g.strip() for g in (user_input.get(CONF_REMOTE_GROUPS) or []) if g.strip()]
            username = (user_input.get(CONF_QUADSTREAM_USERNAME) or "").strip()
            secret = (user_input.get(CONF_QUADSTREAM_SECRET) or "").strip()
            if username:
                try:
                    await async_login(async_get_clientsession(self.hass), username, secret)
                except QuadStreamError:
                    errors["base"] = "quadstream_auth"
                except Exception:  # noqa: BLE001
                    _LOGGER.exception("QuadStream login test failed")
                    errors["base"] = "cannot_connect"
            if not errors:
                user_input[CONF_QUADSTREAM_USERNAME] = username
                user_input[CONF_QUADSTREAM_SECRET] = secret if username else ""
                return self.async_create_entry(title="", data=user_input)
        cur = dict(self.config_entry.options)
        cur.update(user_input or {})
        schema = _options_schema(cur, self._channel_groups(cur.get(CONF_REMOTE_GROUPS) or []), self._own_players())
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)
