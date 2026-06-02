"""Binary sensor platform for Smart Bulb Relay."""

from __future__ import annotations

import logging

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event

from .const import (
    CONF_POWER_SENSOR_ENTITY_ID,
    CONF_POWER_THRESHOLD_W,
    DEFAULT_POWER_THRESHOLD_W,
    DOMAIN,
)
from .registry import device_info_for_id, entry_light_device_id

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    power_sensor_entity_id = entry.options.get(CONF_POWER_SENSOR_ENTITY_ID)
    if not power_sensor_entity_id:
        return

    threshold_w = float(
        entry.options.get(CONF_POWER_THRESHOLD_W, DEFAULT_POWER_THRESHOLD_W)
    )

    device_info: DeviceInfo | None = None
    device = device_info_for_id(hass, entry_light_device_id(hass, entry))
    if device and device.identifiers:
        device_info = DeviceInfo(identifiers=device.identifiers)

    if device_info is None:
        device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
        )

    async_add_entities(
        [
            BulbStatusBinarySensor(
                entry=entry,
                power_sensor_entity_id=power_sensor_entity_id,
                threshold_w=threshold_w,
                device_info=device_info,
            )
        ]
    )


class BulbStatusBinarySensor(BinarySensorEntity):
    """On when the bulb circuit draws more than the configured wattage threshold."""

    _attr_has_entity_name = True
    _attr_device_class = BinarySensorDeviceClass.POWER
    _attr_translation_key = "bulb_status"

    def __init__(
        self,
        entry: ConfigEntry,
        power_sensor_entity_id: str,
        threshold_w: float,
        device_info: DeviceInfo,
    ) -> None:
        self._entry = entry
        self._power_sensor_entity_id = power_sensor_entity_id
        self._threshold_w = threshold_w
        self._attr_device_info = device_info
        self._attr_unique_id = f"{entry.entry_id}_bulb_status"
        self._attr_available = False
        self._attr_is_on = None

    @property
    def suggested_object_id(self) -> str:
        return "bulb_status"

    @property
    def extra_state_attributes(self) -> dict:
        state = self.hass.states.get(self._power_sensor_entity_id)
        attrs: dict = {
            "power_sensor": self._power_sensor_entity_id,
            "threshold_w": self._threshold_w,
        }
        if state and state.state not in ("unavailable", "unknown"):
            try:
                attrs["power_w"] = float(state.state)
            except ValueError:
                pass
        return attrs

    async def async_added_to_hass(self) -> None:
        self._update_from_sensor()
        self.async_on_remove(
            async_track_state_change_event(
                self.hass,
                [self._power_sensor_entity_id],
                self._handle_state_change,
            )
        )

    @callback
    def _handle_state_change(self, event: Event) -> None:
        self._update_from_sensor()
        self.async_write_ha_state()

    @callback
    def _update_from_sensor(self) -> None:
        state = self.hass.states.get(self._power_sensor_entity_id)
        if state is None or state.state in ("unavailable", "unknown"):
            self._attr_available = False
            self._attr_is_on = None
            return
        try:
            self._attr_is_on = float(state.state) > self._threshold_w
            self._attr_available = True
        except ValueError:
            self._attr_available = False
            self._attr_is_on = None
