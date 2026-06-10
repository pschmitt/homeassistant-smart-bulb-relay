"""Smart Bulb Relay integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import (
    CONF_LIGHT_DEVICE_ID,
    CONF_LIGHT_ENTITY_ID,
    CONF_RAISE_REPAIRS,
    CONF_RELAY_DEVICE_ID,
    CONF_RELAY_ENTITY_ID,
    DEFAULT_RAISE_REPAIRS,
    DOMAIN,
)
from .registry import (
    entry_light_device_id,
    entry_relay_device_id,
    resolve_light_entity,
    resolve_relay_entity,
)
from .repairs import BulbReachabilityWatcher
from .services import async_register_services, async_unregister_services

PLATFORMS = ["binary_sensor", "button", "switch"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.setdefault(DOMAIN, {})
    light_entity_id = resolve_light_entity(hass, entry)
    entry_data: dict = {
        "relay": resolve_relay_entity(hass, entry),
        "light": light_entity_id,
        "relay_device": entry_relay_device_id(hass, entry),
        "light_device": entry_light_device_id(hass, entry),
    }
    hass.data[DOMAIN][entry.entry_id] = entry_data
    await async_register_services(hass)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload_on_options_change))

    if entry.options.get(CONF_RAISE_REPAIRS, DEFAULT_RAISE_REPAIRS) and light_entity_id:
        ent_reg = er.async_get(hass)
        bulb_status_entity_id = ent_reg.async_get_entity_id(
            "binary_sensor", DOMAIN, f"{entry.entry_id}_bulb_status"
        )
        watcher = BulbReachabilityWatcher(
            hass,
            entry,
            light_entity_id,
            light_name=entry.title,
            bulb_status_entity_id=bulb_status_entity_id,
        )
        entry_data["watcher"] = watcher
        watcher.start()

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    watcher: BulbReachabilityWatcher | None = (
        hass.data.get(DOMAIN, {}).get(entry.entry_id, {}).get("watcher")
    )
    if watcher:
        watcher.stop()
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
        async_unregister_services(hass)
    return unload_ok


async def _async_reload_on_options_change(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate legacy entity-id based pairings to device-id based pairings."""
    relay_device_id = entry_relay_device_id(hass, entry)
    light_device_id = entry_light_device_id(hass, entry)
    if (
        entry.version > 1
        or not relay_device_id
        or not light_device_id
        or (
            entry.data.get(CONF_RELAY_DEVICE_ID) == relay_device_id
            and entry.data.get(CONF_LIGHT_DEVICE_ID) == light_device_id
        )
    ):
        return True

    data = dict(entry.data)
    data[CONF_RELAY_DEVICE_ID] = relay_device_id
    data[CONF_LIGHT_DEVICE_ID] = light_device_id
    hass.config_entries.async_update_entry(entry, data=data, version=2)
    return True
