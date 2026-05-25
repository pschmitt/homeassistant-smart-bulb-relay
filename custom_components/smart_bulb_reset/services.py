"""Services for the Smart Bulb Reset integration."""

from __future__ import annotations

import asyncio
import logging

import voluptuous as vol

from homeassistant.const import CONF_ENTITY_ID
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv

from .const import (
    CONF_POWER_CYCLE_DELAY,
    DEFAULT_POWER_CYCLE_DELAY,
    DOMAIN,
    SERVICE_POWER_CYCLE,
)

_LOGGER = logging.getLogger(__name__)

_POWER_CYCLE_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_ENTITY_ID): cv.entity_id,
        vol.Optional(
            CONF_POWER_CYCLE_DELAY, default=DEFAULT_POWER_CYCLE_DELAY
        ): vol.All(vol.Coerce(float), vol.Range(min=0.1, max=60.0)),
    }
)


def _relay_for_light(hass: HomeAssistant, light_entity_id: str) -> str | None:
    """Return the relay entity_id paired with the given light, or None."""
    for data in hass.data.get(DOMAIN, {}).values():
        if isinstance(data, dict) and data.get("light") == light_entity_id:
            return data["relay"]
    return None


async def _do_power_cycle(
    hass: HomeAssistant, relay_entity_id: str, delay: float
) -> None:
    _LOGGER.debug("Power-cycling %s (off for %.1f s)", relay_entity_id, delay)
    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": relay_entity_id}, blocking=True
    )
    await asyncio.sleep(delay)
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": relay_entity_id}, blocking=True
    )


async def async_register_services(hass: HomeAssistant) -> None:
    """Register integration services (idempotent)."""
    if hass.services.has_service(DOMAIN, SERVICE_POWER_CYCLE):
        return

    async def _handle_power_cycle(call: ServiceCall) -> None:
        entity_id: str = call.data[CONF_ENTITY_ID]
        delay: float = call.data[CONF_POWER_CYCLE_DELAY]
        entity_domain = entity_id.split(".")[0]

        if entity_domain == "light":
            relay = _relay_for_light(hass, entity_id)
            if relay is None:
                raise ServiceValidationError(
                    translation_domain=DOMAIN,
                    translation_key="no_relay_for_light",
                    translation_placeholders={"entity_id": entity_id},
                )
            await _do_power_cycle(hass, relay, delay)
        elif entity_domain == "switch":
            await _do_power_cycle(hass, entity_id, delay)
        else:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="unsupported_entity",
                translation_placeholders={"entity_id": entity_id},
            )

    hass.services.async_register(
        DOMAIN,
        SERVICE_POWER_CYCLE,
        _handle_power_cycle,
        schema=_POWER_CYCLE_SCHEMA,
    )


def async_unregister_services(hass: HomeAssistant) -> None:
    """Remove services when the last config entry is unloaded."""
    if hass.data.get(DOMAIN):
        return
    if hass.services.has_service(DOMAIN, SERVICE_POWER_CYCLE):
        hass.services.async_remove(DOMAIN, SERVICE_POWER_CYCLE)
