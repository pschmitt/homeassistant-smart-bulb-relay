"""Button platform for Smart Bulb Relay."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DEFAULT_POWER_CYCLE_DELAY,
    DOMAIN,
)
from .registry import (
    device_info_for_id,
    entry_light_device_id,
    resolve_light_entity,
    resolve_relay_entity,
)
from .services import (
    _RESET_SEQUENCE_DEFAULT,
    _do_factory_reset,
    _do_power_cycle,
    _reset_sequence_for_light,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    light_entity_id = resolve_light_entity(hass, entry)
    relay_entity_id = resolve_relay_entity(hass, entry)
    if relay_entity_id is None:
        return

    # Attach our buttons to the existing light device so they show up on its
    # device page alongside the native light entities.
    device_info: DeviceInfo | None = None
    device = device_info_for_id(hass, entry_light_device_id(hass, entry))
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
        light_entity_id: str | None,
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
        light_entity_id: str | None,
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
        light_entity_id: str | None,
        device_info: DeviceInfo,
    ) -> None:
        super().__init__(entry, relay_entity_id, light_entity_id, device_info)
        self._attr_unique_id = f"{entry.entry_id}_factory_reset"

    async def async_press(self) -> None:
        seq = (
            _reset_sequence_for_light(self.hass, self._light_entity_id)
            if self._light_entity_id
            else _RESET_SEQUENCE_DEFAULT
        )
        await _do_factory_reset(self.hass, self._relay_entity_id, **seq)
