"""Smart Bulb Relay integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_LIGHT_ENTITY_ID, CONF_RELAY_ENTITY_ID, DOMAIN
from .services import async_register_services, async_unregister_services


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a relay/bulb pairing from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "relay": entry.data[CONF_RELAY_ENTITY_ID],
        "light": entry.data[CONF_LIGHT_ENTITY_ID],
    }
    await async_register_services(hass)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    hass.data[DOMAIN].pop(entry.entry_id, None)
    async_unregister_services(hass)
    return True
