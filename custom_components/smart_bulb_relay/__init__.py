"""Smart Bulb Relay integration."""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.components import mqtt
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt as dt_util

from .const import (
    CONF_LIGHT_DEVICE_ID,
    CONF_RAISE_REPAIRS,
    CONF_RELAY_DEVICE_ID,
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


_LOGGER = logging.getLogger(__name__)
HEARTBEAT_TOPIC = "homeassistant/shelly-watchdog/heartbeat"


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Send live, non-retained leases only after HA has finished starting."""

    async def publish_heartbeat(_now) -> None:
        if not hass.is_running or not mqtt.is_connected(hass):
            return
        try:
            await mqtt.async_publish(
                hass,
                HEARTBEAT_TOPIC,
                str(int(dt_util.utcnow().timestamp())),
                qos=0,
                retain=False,
            )
        except Exception:  # Keep the timer alive when MQTT disconnects mid-publish.
            _LOGGER.debug("Unable to publish Shelly heartbeat", exc_info=True)

    cancel = async_track_time_interval(hass, publish_heartbeat, timedelta(seconds=5))

    async def stop_heartbeat(_event) -> None:
        cancel()
        if mqtt.is_connected(hass):
            try:
                await mqtt.async_publish(hass, HEARTBEAT_TOPIC, "offline", qos=0, retain=False)
            except Exception:
                _LOGGER.debug("Unable to publish Shelly shutdown", exc_info=True)

    hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, stop_heartbeat)
    return True


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
    else:
        ir.async_delete_issue(hass, DOMAIN, f"light_unreachable_{entry.entry_id}")

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


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove any repair issue when its pairing is deleted."""
    ir.async_delete_issue(hass, DOMAIN, f"light_unreachable_{entry.entry_id}")


async def _async_reload_on_options_change(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate legacy entity-id based pairings to device-id based pairings."""
    if entry.version > 1:
        return True
    relay_device_id = entry_relay_device_id(hass, entry)
    light_device_id = entry_light_device_id(hass, entry)
    if not relay_device_id or not light_device_id:
        # Devices not resolvable (yet) — retry on the next start.
        return True
    if (
        entry.data.get(CONF_RELAY_DEVICE_ID) == relay_device_id
        and entry.data.get(CONF_LIGHT_DEVICE_ID) == light_device_id
    ):
        # Already migrated — record the version so this stops re-running.
        hass.config_entries.async_update_entry(entry, version=2)
        return True

    data = dict(entry.data)
    data[CONF_RELAY_DEVICE_ID] = relay_device_id
    data[CONF_LIGHT_DEVICE_ID] = light_device_id
    hass.config_entries.async_update_entry(entry, data=data, version=2)
    return True
