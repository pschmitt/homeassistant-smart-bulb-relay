"""Registry helpers for Smart Bulb Relay."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .const import (
    CONF_LIGHT_DEVICE_ID,
    CONF_LIGHT_ENTITY_ID,
    CONF_RELAY_DEVICE_ID,
    CONF_RELAY_ENTITY_ID,
)


def effective_entry_value(entry: ConfigEntry, key: str) -> str | None:
    """Return effective config value for key, honoring options overrides."""
    return entry.options.get(key) or entry.data.get(key)


def device_id_for_entity(hass: HomeAssistant, entity_id: str | None) -> str | None:
    """Return device_id for an entity_id."""
    if not entity_id:
        return None
    entity_entry = er.async_get(hass).async_get(entity_id)
    return entity_entry.device_id if entity_entry else None


def entry_relay_device_id(hass: HomeAssistant, entry: ConfigEntry) -> str | None:
    """Return the configured relay device id, migrating from entity data if needed."""
    return effective_entry_value(entry, CONF_RELAY_DEVICE_ID) or device_id_for_entity(
        hass,
        effective_entry_value(entry, CONF_RELAY_ENTITY_ID),
    )


def entry_light_device_id(hass: HomeAssistant, entry: ConfigEntry) -> str | None:
    """Return the configured light device id, migrating from entity data if needed."""
    return effective_entry_value(entry, CONF_LIGHT_DEVICE_ID) or device_id_for_entity(
        hass,
        effective_entry_value(entry, CONF_LIGHT_ENTITY_ID),
    )


def resolve_device_entity(
    hass: HomeAssistant,
    device_id: str | None,
    domain: str,
    *,
    platform: str | None = None,
) -> str | None:
    """Resolve an enabled entity for a device/domain pair."""
    if not device_id:
        return None
    for entity_entry in er.async_get(hass).entities.values():
        if entity_entry.device_id != device_id:
            continue
        if entity_entry.disabled_by is not None:
            continue
        if entity_entry.entity_id.split(".", 1)[0] != domain:
            continue
        if platform is not None and entity_entry.platform != platform:
            continue
        return entity_entry.entity_id
    return None


def resolve_relay_entity(hass: HomeAssistant, entry: ConfigEntry) -> str | None:
    """Resolve the current switch entity for an entry's relay device."""
    resolved = resolve_device_entity(
        hass,
        entry_relay_device_id(hass, entry),
        "switch",
        platform="shelly",
    )
    if resolved:
        return resolved
    legacy_entity_id = effective_entry_value(entry, CONF_RELAY_ENTITY_ID)
    if legacy_entity_id and er.async_get(hass).async_get(legacy_entity_id):
        return legacy_entity_id
    return None


def resolve_light_entity(hass: HomeAssistant, entry: ConfigEntry) -> str | None:
    """Resolve the current light entity for an entry's bulb device."""
    resolved = resolve_device_entity(
        hass,
        entry_light_device_id(hass, entry),
        "light",
    )
    if resolved:
        return resolved
    legacy_entity_id = effective_entry_value(entry, CONF_LIGHT_ENTITY_ID)
    if legacy_entity_id and er.async_get(hass).async_get(legacy_entity_id):
        return legacy_entity_id
    return None


def device_info_for_id(
    hass: HomeAssistant,
    device_id: str | None,
) -> dr.DeviceEntry | None:
    """Return a device registry entry."""
    if device_id is None:
        return None
    return dr.async_get(hass).async_get(device_id)
