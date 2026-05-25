"""Smart Bulb Reset integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_LIGHT_ENTITY_ID, CONF_RELAY_ENTITY_ID, DOMAIN
from .services import async_register_services, async_unregister_services


def _effective(entry: ConfigEntry, key: str) -> str:
    """Return value from options if overridden there, else from data."""
    return entry.options.get(key) or entry.data[key]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a relay/bulb pairing from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "relay": _effective(entry, CONF_RELAY_ENTITY_ID),
        "light": _effective(entry, CONF_LIGHT_ENTITY_ID),
    }
    await async_register_services(hass)
    entry.async_on_unload(entry.add_update_listener(_async_reload_on_options_change))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    hass.data[DOMAIN].pop(entry.entry_id, None)
    async_unregister_services(hass)
    return True


async def _async_reload_on_options_change(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry so updated options take effect immediately."""
    await hass.config_entries.async_reload(entry.entry_id)
