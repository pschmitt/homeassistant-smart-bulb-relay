"""Switch platform for Smart Bulb Relay."""

from __future__ import annotations

import json
import logging
from datetime import timedelta
from typing import Any

from aiohttp import ClientError, ClientTimeout

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import slugify

from .const import (
    CONF_SMART_MODE_ENABLED,
    DEFAULT_SMART_MODE_ENABLED,
    DOMAIN,
    SHELLY_WATCHDOG_FORCE_FALLBACK_KEY,
)
from .registry import (
    entry_light_device_id,
    entry_relay_device_id,
    resolve_light_entity,
    resolve_relay_entity,
)

SCAN_INTERVAL = timedelta(seconds=60)
_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    if not entry.options.get(CONF_SMART_MODE_ENABLED, DEFAULT_SMART_MODE_ENABLED):
        return

    relay_entity_id = resolve_relay_entity(hass, entry)
    relay_device_id = entry_relay_device_id(hass, entry)
    light_entity_id = resolve_light_entity(hass, entry)
    light_device_id = entry_light_device_id(hass, entry)

    device_reg = dr.async_get(hass)
    shelly_device = device_reg.async_get(relay_device_id) if relay_device_id else None
    if shelly_device is None:
        _LOGGER.warning(
            "Cannot create smart-mode switch for %s: relay device not found",
            entry.title,
        )
        return

    if not _entry_owns_relay_switch(hass, entry, relay_device_id):
        return

    shelly_entry = _shelly_config_entry(hass, shelly_device)
    if shelly_entry is None:
        _LOGGER.warning(
            "Cannot create smart-mode switch for %s: Shelly config entry not found",
            relay_entity_id,
        )
        return

    async_add_entities(
        [
            ShellySmartModeSwitch(
                entry=entry,
                relay_device_id=relay_device_id,
                relay_entity_id=relay_entity_id,
                light_device_id=light_device_id,
                light_entity_id=light_entity_id,
                shelly_device=shelly_device,
                shelly_entry=shelly_entry,
            )
        ],
        update_before_add=True,
    )


def _shelly_config_entry(
    hass: HomeAssistant,
    device: dr.DeviceEntry,
) -> ConfigEntry | None:
    for entry_id in device.config_entries:
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry and entry.domain == "shelly":
            return entry
    return None


def _entry_owns_relay_switch(
    hass: HomeAssistant,
    entry: ConfigEntry,
    relay_device_id: str,
) -> bool:
    """Return True for the first configured pairing that uses this relay."""
    owners = [
        config_entry.entry_id
        for config_entry in hass.config_entries.async_entries(DOMAIN)
        if entry_relay_device_id(hass, config_entry) == relay_device_id
    ]
    return bool(owners) and entry.entry_id == sorted(owners)[0]


class ShellySmartModeSwitch(SwitchEntity):
    """Expose the Shelly watchdog forced-fallback KVS flag as smart mode."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = "smart_mode"

    def __init__(
        self,
        entry: ConfigEntry,
        relay_device_id: str,
        relay_entity_id: str | None,
        light_device_id: str | None,
        light_entity_id: str | None,
        shelly_device: dr.DeviceEntry,
        shelly_entry: ConfigEntry,
    ) -> None:
        self._entry = entry
        self._relay_device_id = relay_device_id
        self._relay_entity_id = relay_entity_id
        self._light_device_id = light_device_id
        self._light_entity_id = light_entity_id
        self._shelly_device_id = shelly_device.id
        self._shelly_entry = shelly_entry
        self._attr_unique_id = f"{relay_device_id}_smart_mode"
        self._attr_device_info = DeviceInfo(identifiers=shelly_device.identifiers)
        self.entity_id = f"switch.{slugify(shelly_device.name_by_user or shelly_device.name)}_smart_mode"
        self._attr_extra_state_attributes = {
            "relay_device_id": relay_device_id,
            "relay_entity_id": relay_entity_id,
            "light_device_id": light_device_id,
            "light_entity_id": light_entity_id,
            "kvs_key": SHELLY_WATCHDOG_FORCE_FALLBACK_KEY,
        }
        self._attr_available = False
        self._attr_is_on: bool | None = None

    @property
    def _host(self) -> str | None:
        host = self._shelly_entry.data.get("host")
        if not host:
            return None
        port = self._shelly_entry.data.get("port")
        if port and str(port) != "80":
            return f"{host}:{port}"
        return str(host)

    async def async_update(self) -> None:
        """Refresh the smart-mode state from Shelly KVS."""
        value = await self._shelly_rpc("KVS.Get", {"key": SHELLY_WATCHDOG_FORCE_FALLBACK_KEY})
        if value is None:
            self._attr_available = False
            return

        if "code" in value and value.get("code") != -105:
            self._attr_available = False
            return

        forced_fallback = value.get("value") == "true"
        self._attr_is_on = not forced_fallback
        self._attr_available = True

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Clear forced fallback so the watchdog may use detached input mode."""
        await self._set_forced_fallback(False)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Force fallback so the Shelly behaves like a normal wall switch."""
        await self._set_forced_fallback(True)

    async def _set_forced_fallback(self, forced: bool) -> None:
        await self.hass.services.async_call(
            "shelly",
            "set_kvs_value",
            {
                "device_id": self._shelly_device_id,
                "key": SHELLY_WATCHDOG_FORCE_FALLBACK_KEY,
                "value": "true" if forced else "false",
            },
            blocking=True,
        )
        reachable = await self._restart_watchdog_script()
        self._attr_is_on = not forced
        self._attr_available = reachable
        self.async_write_ha_state()

    async def _restart_watchdog_script(self) -> bool:
        """Restart ha-watchdog so it picks up the new KVS value immediately."""
        scripts = await self._shelly_rpc("Script.List", {})
        if scripts is None:
            return False
        script_id = next(
            (s["id"] for s in scripts.get("scripts", []) if s.get("name") == "ha-watchdog"),
            None,
        )
        if script_id is None:
            _LOGGER.warning(
                "ha-watchdog script not found on %s",
                self._relay_entity_id or self._relay_device_id,
            )
            return False
        await self._shelly_rpc("Script.Stop", {"id": script_id})
        result = await self._shelly_rpc("Script.Start", {"id": script_id})
        return result is not None

    async def _shelly_rpc(
        self,
        method: str,
        params: dict[str, Any],
    ) -> dict[str, Any] | None:
        host = self._host
        if host is None:
            return None

        session = async_get_clientsession(self.hass)
        timeout = ClientTimeout(total=10)
        try:
            async with session.post(
                f"http://{host}/rpc/{method}",
                json=params,
                timeout=timeout,
            ) as response:
                try:
                    data = await response.json(content_type=None)
                except json.JSONDecodeError:
                    data = {}

                if response.status >= 400 and data.get("code") == -105:
                    return data

                if response.status >= 400:
                    _LOGGER.warning(
                        "Shelly RPC %s failed for %s: HTTP %s",
                        method,
                        self._relay_entity_id or self._relay_device_id,
                        response.status,
                    )
                    return None
                return data if isinstance(data, dict) else {}
        except (ClientError, TimeoutError) as err:
            _LOGGER.debug(
                "Shelly RPC %s failed for %s: %s",
                method,
                self._relay_entity_id or self._relay_device_id,
                err,
            )
            return None
