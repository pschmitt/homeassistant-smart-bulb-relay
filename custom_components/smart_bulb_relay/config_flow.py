"""Config flow for Smart Bulb Relay."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .const import (
    CONF_LIGHT_ENTITY_ID,
    CONF_RELAY_ENTITY_ID,
    DOMAIN,
    SUPPORTED_LIGHT_MANUFACTURER_KEYWORDS,
)

_LOGGER = logging.getLogger(__name__)


def _entity_area_id(
    entry: er.RegistryEntry, device_reg: dr.DeviceRegistry
) -> str | None:
    """Return the effective area_id for an entity (entity override → device fallback)."""
    if entry.area_id:
        return entry.area_id
    if entry.device_id:
        device = device_reg.async_get(entry.device_id)
        if device:
            return device.area_id
    return None


def _is_supported_light(
    entry: er.RegistryEntry, device_reg: dr.DeviceRegistry
) -> bool:
    """Return True if the light entity belongs to a supported manufacturer (IKEA/Hue)."""
    if not entry.device_id:
        return False
    device = device_reg.async_get(entry.device_id)
    if not device or not device.manufacturer:
        return False
    m = device.manufacturer.lower()
    return any(kw in m for kw in SUPPORTED_LIGHT_MANUFACTURER_KEYWORDS)


def _display_name(entry: er.RegistryEntry) -> str:
    return entry.name or entry.original_name or entry.entity_id


def _discover_candidates(
    entity_reg: er.EntityRegistry,
    device_reg: dr.DeviceRegistry,
    existing_relays: set[str],
) -> list[tuple[er.RegistryEntry, er.RegistryEntry]]:
    """Return area-matched (relay_switch, smart_light) pairs not yet configured."""
    shelly_switches: list[er.RegistryEntry] = []
    smart_lights: list[er.RegistryEntry] = []

    for entry in entity_reg.entities.values():
        if entry.disabled_by:
            continue
        entity_domain = entry.entity_id.split(".")[0]
        if (
            entity_domain == "switch"
            and entry.platform == "shelly"
            and entry.entity_id not in existing_relays
        ):
            shelly_switches.append(entry)
        elif entity_domain == "light" and _is_supported_light(entry, device_reg):
            smart_lights.append(entry)

    # Index lights by area
    lights_by_area: dict[str, list[er.RegistryEntry]] = {}
    for light in smart_lights:
        area_id = _entity_area_id(light, device_reg)
        if area_id:
            lights_by_area.setdefault(area_id, []).append(light)

    candidates: list[tuple[er.RegistryEntry, er.RegistryEntry]] = []
    for switch in shelly_switches:
        area_id = _entity_area_id(switch, device_reg)
        if area_id and area_id in lights_by_area:
            for light in lights_by_area[area_id]:
                candidates.append((switch, light))

    return candidates


class SmartBulbRelayConfigFlow(ConfigFlow, domain=DOMAIN):
    """Config flow for Smart Bulb Relay."""

    VERSION = 1

    @property
    def _configured_relays(self) -> set[str]:
        return {
            e.data[CONF_RELAY_ENTITY_ID]
            for e in self._async_current_entries()
            if CONF_RELAY_ENTITY_ID in e.data
        }

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            if user_input["setup_type"] == "auto":
                return await self.async_step_auto_discover()
            return await self.async_step_manual()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required("setup_type", default="auto"): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                SelectOptionDict(value="auto", label="Auto-discover"),
                                SelectOptionDict(value="manual", label="Manual"),
                            ],
                            mode=SelectSelectorMode.LIST,
                        )
                    )
                }
            ),
        )

    async def async_step_auto_discover(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entity_reg = er.async_get(self.hass)
        device_reg = dr.async_get(self.hass)
        candidates = _discover_candidates(entity_reg, device_reg, self._configured_relays)

        if not candidates:
            _LOGGER.debug(
                "Auto-discover: no area-matched Shelly+IKEA/Hue pairs found; "
                "falling back to manual setup"
            )
            return await self.async_step_manual()

        if user_input is not None:
            relay_id, light_id = user_input["pairing"].split("|", 1)
            return await self._async_create_entry(relay_id, light_id)

        options = [
            SelectOptionDict(
                value=f"{sw.entity_id}|{lt.entity_id}",
                label=f"{_display_name(sw)} → {_display_name(lt)}",
            )
            for sw, lt in candidates
        ]
        return self.async_show_form(
            step_id="auto_discover",
            data_schema=vol.Schema(
                {
                    vol.Required("pairing"): SelectSelector(
                        SelectSelectorConfig(
                            options=options, mode=SelectSelectorMode.LIST
                        )
                    )
                }
            ),
        )

    async def async_step_manual(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return await self._async_create_entry(
                user_input[CONF_RELAY_ENTITY_ID],
                user_input[CONF_LIGHT_ENTITY_ID],
            )

        return self.async_show_form(
            step_id="manual",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_RELAY_ENTITY_ID): EntitySelector(
                        EntitySelectorConfig(domain="switch")
                    ),
                    vol.Required(CONF_LIGHT_ENTITY_ID): EntitySelector(
                        EntitySelectorConfig(domain="light")
                    ),
                }
            ),
        )

    async def _async_create_entry(
        self, relay_entity_id: str, light_entity_id: str
    ) -> ConfigFlowResult:
        await self.async_set_unique_id(f"{relay_entity_id}__{light_entity_id}")
        self._abort_if_unique_id_configured()

        entity_reg = er.async_get(self.hass)
        light_entry = entity_reg.async_get(light_entity_id)
        title = _display_name(light_entry) if light_entry else light_entity_id

        return self.async_create_entry(
            title=title,
            data={
                CONF_RELAY_ENTITY_ID: relay_entity_id,
                CONF_LIGHT_ENTITY_ID: light_entity_id,
            },
        )
