"""Services for the Smart Bulb Relay integration."""

from __future__ import annotations

import asyncio
import logging
from typing import NamedTuple

import voluptuous as vol

from homeassistant.const import CONF_ENTITY_ID
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_track_state_change_event

from .const import (
    CONF_BRIGHTNESS_PCT,
    CONF_COLOR_TEMP_KELVIN,
    CONF_LIGHT_CONTROL_TIMEOUT,
    CONF_POWER_CYCLE_DELAY,
    DEFAULT_BRIGHTNESS_PCT,
    DEFAULT_LIGHT_CONTROL_TIMEOUT,
    DEFAULT_POWER_CYCLE_DELAY,
    DOMAIN,
    SERVICE_FACTORY_RESET,
    SERVICE_POWER_CYCLE,
    SERVICE_TOGGLE,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
)
from .registry import (
    device_id_for_entity,
    entry_light_device_id,
    entry_relay_device_id,
    resolve_device_entity,
    resolve_light_entity,
    resolve_relay_entity,
)

_LOGGER = logging.getLogger(__name__)

CONF_DEVICE_ID = "device_id"
CONF_TOGGLE_COUNT = "toggle_count"
CONF_OFF_DURATION = "off_duration"
CONF_ON_DURATION = "on_duration"

_TARGET_FIELDS = {
    vol.Optional(CONF_ENTITY_ID): vol.Any(cv.entity_id, [cv.entity_id]),
    vol.Optional(CONF_DEVICE_ID): vol.Any(str, [str]),
}

_POWER_CYCLE_SCHEMA = vol.Schema(
    {
        **_TARGET_FIELDS,
        vol.Optional(
            CONF_POWER_CYCLE_DELAY, default=DEFAULT_POWER_CYCLE_DELAY
        ): vol.All(vol.Coerce(float), vol.Range(min=0.1, max=60.0)),
    },
    extra=vol.ALLOW_EXTRA,
)

_FACTORY_RESET_SCHEMA = vol.Schema(
    {
        **_TARGET_FIELDS,
        vol.Optional(CONF_TOGGLE_COUNT): vol.All(int, vol.Range(min=1, max=20)),
        vol.Optional(CONF_OFF_DURATION): vol.All(
            vol.Coerce(float), vol.Range(min=0.1, max=30.0)
        ),
        vol.Optional(CONF_ON_DURATION): vol.All(
            vol.Coerce(float), vol.Range(min=0.1, max=30.0)
        ),
    },
    extra=vol.ALLOW_EXTRA,
)

_TURN_ON_SCHEMA = vol.Schema(
    {
        **_TARGET_FIELDS,
        vol.Optional(CONF_BRIGHTNESS_PCT, default=DEFAULT_BRIGHTNESS_PCT): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=100)
        ),
        vol.Optional(CONF_COLOR_TEMP_KELVIN): vol.All(
            vol.Coerce(int), vol.Range(min=1000, max=10000)
        ),
        vol.Optional(
            CONF_LIGHT_CONTROL_TIMEOUT, default=DEFAULT_LIGHT_CONTROL_TIMEOUT
        ): vol.All(vol.Coerce(float), vol.Range(min=0.1, max=30.0)),
    },
    extra=vol.ALLOW_EXTRA,
)

_TURN_OFF_SCHEMA = vol.Schema(
    {
        **_TARGET_FIELDS,
        vol.Optional(
            CONF_LIGHT_CONTROL_TIMEOUT, default=DEFAULT_LIGHT_CONTROL_TIMEOUT
        ): vol.All(vol.Coerce(float), vol.Range(min=0.1, max=30.0)),
    },
    extra=vol.ALLOW_EXTRA,
)

_TOGGLE_SCHEMA = _TURN_ON_SCHEMA

# Power-cycling sequences for factory reset, keyed by manufacturer keyword.
_RESET_SEQUENCES: dict[str, dict] = {
    "ikea":    {"toggle_count": 6, "off_duration": 2.0, "on_duration": 2.0},
    "philips": {"toggle_count": 3, "off_duration": 5.0, "on_duration": 5.0},
    "signify": {"toggle_count": 3, "off_duration": 5.0, "on_duration": 5.0},
}
_RESET_SEQUENCE_DEFAULT = {"toggle_count": 6, "off_duration": 2.0, "on_duration": 2.0}


# ---------------------------------------------------------------------------
# Target resolution
# ---------------------------------------------------------------------------

class _RelayTarget(NamedTuple):
    relay: str
    light_entity_id: str | None


def _relay_for_light(hass: HomeAssistant, light_entity_id: str) -> str | None:
    light_device_id = device_id_for_entity(hass, light_entity_id)
    for entry in hass.config_entries.async_entries(DOMAIN):
        configured_light_device = entry_light_device_id(hass, entry)
        if configured_light_device and configured_light_device == light_device_id:
            return resolve_relay_entity(hass, entry)
        if not configured_light_device:
            data = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
            if isinstance(data, dict) and data.get("light") == light_entity_id:
                return data["relay"]
    return None


def _resolve_targets(hass: HomeAssistant, call_data: dict) -> list[_RelayTarget]:
    targets: list[_RelayTarget] = []
    seen_relays: set[str] = set()

    def _add(relay: str, light: str | None) -> None:
        if relay not in seen_relays:
            seen_relays.add(relay)
            targets.append(_RelayTarget(relay=relay, light_entity_id=light))

    raw_eid = call_data.get(CONF_ENTITY_ID)
    if raw_eid:
        eids = [raw_eid] if isinstance(raw_eid, str) else list(raw_eid)
        for eid in eids:
            domain = eid.split(".")[0]
            if domain == "light":
                relay = _relay_for_light(hass, eid)
                if relay is None:
                    raise ServiceValidationError(
                        translation_domain=DOMAIN,
                        translation_key="no_relay_for_light",
                        translation_placeholders={"entity_id": eid},
                    )
                _add(relay, eid)
            elif domain == "switch":
                _add(eid, None)
            else:
                raise ServiceValidationError(
                    translation_domain=DOMAIN,
                    translation_key="unsupported_entity",
                    translation_placeholders={"entity_id": eid},
                )

    raw_did = call_data.get(CONF_DEVICE_ID)
    if raw_did:
        dids = [raw_did] if isinstance(raw_did, str) else list(raw_did)
        for did in dids:
            found = False
            for config_entry in hass.config_entries.async_entries(DOMAIN):
                relay_device = entry_relay_device_id(hass, config_entry)
                light_device = entry_light_device_id(hass, config_entry)
                if light_device == did:
                    relay = resolve_relay_entity(hass, config_entry)
                    light = resolve_light_entity(hass, config_entry)
                    if relay:
                        _add(relay, light)
                        found = True
                elif relay_device == did:
                    relay = resolve_relay_entity(hass, config_entry)
                    if relay:
                        _add(relay, None)
                        found = True
            if not found:
                for entry in er.async_get(hass).entities.values():
                    if entry.device_id != did or entry.entity_id.split(".")[0] != "light":
                        continue
                    relay = _relay_for_light(hass, entry.entity_id)
                    if relay:
                        _add(relay, entry.entity_id)
                        found = True
            if not found:
                relay = resolve_device_entity(hass, did, "switch", platform="shelly")
                if relay:
                    _add(relay, None)
                    found = True
            if not found:
                raise ServiceValidationError(
                    translation_domain=DOMAIN,
                    translation_key="no_relay_for_device",
                    translation_placeholders={"device_id": did},
                )

    return targets


def _require_targets(hass: HomeAssistant, call_data: dict) -> list[_RelayTarget]:
    targets = _resolve_targets(hass, call_data)
    if not targets:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="no_target_specified"
        )
    return targets


# ---------------------------------------------------------------------------
# Manufacturer detection (for factory reset)
# ---------------------------------------------------------------------------

def _reset_sequence_for_light(hass: HomeAssistant, light_entity_id: str) -> dict:
    entity_reg = er.async_get(hass)
    entry = entity_reg.async_get(light_entity_id)
    if not entry or not entry.device_id:
        return _RESET_SEQUENCE_DEFAULT
    device_reg = dr.async_get(hass)
    device = device_reg.async_get(entry.device_id)
    if not device or not device.manufacturer:
        return _RESET_SEQUENCE_DEFAULT
    mfr = device.manufacturer.lower()
    for kw, seq in _RESET_SEQUENCES.items():
        if kw in mfr:
            return seq
    return _RESET_SEQUENCE_DEFAULT


# ---------------------------------------------------------------------------
# State helpers
# ---------------------------------------------------------------------------

def _is_available(hass: HomeAssistant, entity_id: str) -> bool:
    state = hass.states.get(entity_id)
    return state is not None and state.state not in ("unavailable", "unknown")


def _is_on(hass: HomeAssistant, entity_id: str) -> bool:
    state = hass.states.get(entity_id)
    return state is not None and state.state == "on"


async def _wait_for_state(
    hass: HomeAssistant, entity_id: str, expected_state: str, timeout: float
) -> bool:
    """Return True if entity reaches expected_state within timeout (event-driven)."""
    if hass.states.get(entity_id) and hass.states.get(entity_id).state == expected_state:
        return True

    done: asyncio.Future[bool] = hass.loop.create_future()

    @callback
    def _listener(event: object) -> None:
        new_state = event.data.get("new_state")  # type: ignore[union-attr]
        if new_state and new_state.state == expected_state and not done.done():
            done.set_result(True)

    unsub = async_track_state_change_event(hass, [entity_id], _listener)
    try:
        return await asyncio.wait_for(done, timeout=timeout)
    except asyncio.TimeoutError:
        return False
    finally:
        unsub()
        if not done.done():
            done.cancel()


# ---------------------------------------------------------------------------
# Low-level relay operations
# ---------------------------------------------------------------------------

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


async def _do_factory_reset(
    hass: HomeAssistant,
    relay_entity_id: str,
    toggle_count: int,
    off_duration: float,
    on_duration: float,
) -> None:
    _LOGGER.debug(
        "Factory reset on %s: %d toggles (off %.1fs / on %.1fs)",
        relay_entity_id, toggle_count, off_duration, on_duration,
    )
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": relay_entity_id}, blocking=True
    )
    await asyncio.sleep(on_duration)
    for i in range(toggle_count):
        await hass.services.async_call(
            "switch", "turn_off", {"entity_id": relay_entity_id}, blocking=True
        )
        await asyncio.sleep(off_duration)
        await hass.services.async_call(
            "switch", "turn_on", {"entity_id": relay_entity_id}, blocking=True
        )
        if i < toggle_count - 1:
            await asyncio.sleep(on_duration)


# ---------------------------------------------------------------------------
# Smart light control (relay + light, with fallback logic)
# ---------------------------------------------------------------------------

async def _do_turn_on(
    hass: HomeAssistant,
    relay: str,
    light: str | None,
    brightness_pct: int,
    color_temp_kelvin: int | None,
    timeout: float,
) -> None:
    if light is None:
        await hass.services.async_call("switch", "turn_on", {"entity_id": relay}, blocking=True)
        return

    light_available = _is_available(hass, light)
    relay_on = _is_on(hass, relay)

    if not light_available:
        if not relay_on:
            # Relay off and light unavailable → just turn relay on.
            await hass.services.async_call("switch", "turn_on", {"entity_id": relay}, blocking=True)
        else:
            # Relay already on but light unresponsive → power cycle to recover.
            _LOGGER.debug("turn_on: %s unavailable, power-cycling relay %s", light, relay)
            await _do_power_cycle(hass, relay, DEFAULT_POWER_CYCLE_DELAY)
        return

    # Light is available.
    if not relay_on:
        await hass.services.async_call("switch", "turn_on", {"entity_id": relay}, blocking=True)

    data: dict = {"entity_id": light, "brightness_pct": brightness_pct}
    if color_temp_kelvin is not None:
        data["color_temp_kelvin"] = color_temp_kelvin
    await hass.services.async_call("light", "turn_on", data, blocking=True)

    if not await _wait_for_state(hass, light, "on", timeout):
        _LOGGER.debug("turn_on: %s did not respond, power-cycling relay %s", light, relay)
        await _do_power_cycle(hass, relay, DEFAULT_POWER_CYCLE_DELAY)


async def _do_turn_off(
    hass: HomeAssistant,
    relay: str,
    light: str | None,
    timeout: float,
) -> None:
    if light is None:
        await hass.services.async_call("switch", "turn_off", {"entity_id": relay}, blocking=True)
        return

    relay_on = _is_on(hass, relay)
    if not relay_on:
        return  # already off

    if not _is_available(hass, light):
        # Light unavailable → kill the relay directly.
        await hass.services.async_call("switch", "turn_off", {"entity_id": relay}, blocking=True)
        return

    await hass.services.async_call("light", "turn_off", {"entity_id": light}, blocking=True)

    if not await _wait_for_state(hass, light, "off", timeout):
        _LOGGER.debug("turn_off: %s did not respond, turning off relay %s", light, relay)
        await hass.services.async_call("switch", "turn_off", {"entity_id": relay}, blocking=True)


async def _do_toggle(
    hass: HomeAssistant,
    relay: str,
    light: str | None,
    brightness_pct: int,
    color_temp_kelvin: int | None,
    timeout: float,
) -> None:
    if light is None:
        await hass.services.async_call("switch", "toggle", {"entity_id": relay}, blocking=True)
        return

    state = hass.states.get(light)
    light_on = state is not None and state.state == "on"

    if light_on:
        await _do_turn_off(hass, relay, light, timeout)
    else:
        await _do_turn_on(hass, relay, light, brightness_pct, color_temp_kelvin, timeout)


# ---------------------------------------------------------------------------
# Service registration
# ---------------------------------------------------------------------------

_ALL_SERVICES = (
    SERVICE_POWER_CYCLE,
    SERVICE_FACTORY_RESET,
    SERVICE_TURN_ON,
    SERVICE_TURN_OFF,
    SERVICE_TOGGLE,
)


async def async_register_services(hass: HomeAssistant) -> None:
    """Register integration services (idempotent)."""
    if hass.services.has_service(DOMAIN, SERVICE_POWER_CYCLE):
        return

    async def _handle_power_cycle(call: ServiceCall) -> None:
        delay: float = call.data.get(CONF_POWER_CYCLE_DELAY, DEFAULT_POWER_CYCLE_DELAY)
        for t in _require_targets(hass, call.data):
            await _do_power_cycle(hass, t.relay, delay)

    async def _handle_factory_reset(call: ServiceCall) -> None:
        for t in _require_targets(hass, call.data):
            seq = (
                _reset_sequence_for_light(hass, t.light_entity_id)
                if t.light_entity_id
                else _RESET_SEQUENCE_DEFAULT
            )
            await _do_factory_reset(
                hass,
                t.relay,
                toggle_count=call.data.get(CONF_TOGGLE_COUNT, seq["toggle_count"]),
                off_duration=call.data.get(CONF_OFF_DURATION, seq["off_duration"]),
                on_duration=call.data.get(CONF_ON_DURATION, seq["on_duration"]),
            )

    async def _handle_turn_on(call: ServiceCall) -> None:
        brightness_pct: int = call.data.get(CONF_BRIGHTNESS_PCT, DEFAULT_BRIGHTNESS_PCT)
        color_temp_kelvin: int | None = call.data.get(CONF_COLOR_TEMP_KELVIN)
        timeout: float = call.data.get(CONF_LIGHT_CONTROL_TIMEOUT, DEFAULT_LIGHT_CONTROL_TIMEOUT)
        for t in _require_targets(hass, call.data):
            await _do_turn_on(hass, t.relay, t.light_entity_id, brightness_pct, color_temp_kelvin, timeout)

    async def _handle_turn_off(call: ServiceCall) -> None:
        timeout: float = call.data.get(CONF_LIGHT_CONTROL_TIMEOUT, DEFAULT_LIGHT_CONTROL_TIMEOUT)
        for t in _require_targets(hass, call.data):
            await _do_turn_off(hass, t.relay, t.light_entity_id, timeout)

    async def _handle_toggle(call: ServiceCall) -> None:
        brightness_pct: int = call.data.get(CONF_BRIGHTNESS_PCT, DEFAULT_BRIGHTNESS_PCT)
        color_temp_kelvin: int | None = call.data.get(CONF_COLOR_TEMP_KELVIN)
        timeout: float = call.data.get(CONF_LIGHT_CONTROL_TIMEOUT, DEFAULT_LIGHT_CONTROL_TIMEOUT)
        for t in _require_targets(hass, call.data):
            await _do_toggle(hass, t.relay, t.light_entity_id, brightness_pct, color_temp_kelvin, timeout)

    hass.services.async_register(DOMAIN, SERVICE_POWER_CYCLE,   _handle_power_cycle,   schema=_POWER_CYCLE_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_FACTORY_RESET, _handle_factory_reset, schema=_FACTORY_RESET_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_TURN_ON,       _handle_turn_on,       schema=_TURN_ON_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_TURN_OFF,      _handle_turn_off,      schema=_TURN_OFF_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_TOGGLE,        _handle_toggle,        schema=_TOGGLE_SCHEMA)


def async_unregister_services(hass: HomeAssistant) -> None:
    """Remove services when the last config entry is unloaded."""
    if hass.data.get(DOMAIN):
        return
    for svc in _ALL_SERVICES:
        if hass.services.has_service(DOMAIN, svc):
            hass.services.async_remove(DOMAIN, svc)
