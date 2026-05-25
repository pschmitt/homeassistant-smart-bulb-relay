"""Button platform for Smart Bulb Reset."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_LIGHT_ENTITY_ID,
    CONF_RELAY_ENTITY_ID,
    DEFAULT_POWER_CYCLE_DELAY,
    DOMAIN,
)
from .services import _do_factory_reset, _do_power_cycle, _reset_sequence_for_light


def _effective(entry: ConfigEntry, key: str) -> str:
    return entry.options.get(key) or entry.data[key]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    light_entity_id = _effective(entry, CONF_LIGHT_ENTITY_ID)
    relay_entity_id = _effective(entry, CONF_RELAY_ENTITY_ID)

    # Attach our buttons to the existing light device so they show up on its
    # device page alongside the native light entities.
    entity_reg = er.async_get(hass)
    device_reg = dr.async_get(hass)
    device_info: DeviceInfo | None = None
    light_entry = entity_reg.async_get(light_entity_id)
    if light_entry and light_entry.device_id:
        device = device_reg.async_get(light_entry.device_id)
        if device and device.identifiers:
            device_info = DeviceInfo(identifiers=device.identifiers)

    # Fallback: create a standalone device for this pairing.
    if device_info is None:
        device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
        )

    async_add_entities(
        [
            PowerCycleButton(entry, relay_entity_id, light_entity_id, device_info),
            FactoryResetButton(entry, relay_entity_id, light_entity_id, device_info),
        ]
    )


class _SmartBulbButton(ButtonEntity):
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        entry: ConfigEntry,
        relay_entity_id: str,
        light_entity_id: str,
        device_info: DeviceInfo,
    ) -> None:
        self._entry = entry
        self._relay_entity_id = relay_entity_id
        self._light_entity_id = light_entity_id
        self._attr_device_info = device_info


class PowerCycleButton(_SmartBulbButton):
    _attr_translation_key = "power_cycle"

    def __init__(
        self,
        entry: ConfigEntry,
        relay_entity_id: str,
        light_entity_id: str,
        device_info: DeviceInfo,
    ) -> None:
        super().__init__(entry, relay_entity_id, light_entity_id, device_info)
        self._attr_unique_id = f"{entry.entry_id}_power_cycle"

    async def async_press(self) -> None:
        await _do_power_cycle(self.hass, self._relay_entity_id, DEFAULT_POWER_CYCLE_DELAY)


class FactoryResetButton(_SmartBulbButton):
    _attr_translation_key = "factory_reset"

    def __init__(
        self,
        entry: ConfigEntry,
        relay_entity_id: str,
        light_entity_id: str,
        device_info: DeviceInfo,
    ) -> None:
        super().__init__(entry, relay_entity_id, light_entity_id, device_info)
        self._attr_unique_id = f"{entry.entry_id}_factory_reset"

    async def async_press(self) -> None:
        seq = _reset_sequence_for_light(self.hass, self._light_entity_id)
        await _do_factory_reset(self.hass, self._relay_entity_id, **seq)
