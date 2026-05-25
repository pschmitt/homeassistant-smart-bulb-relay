"""Services for the Smart Bulb Reset integration."""

from __future__ import annotations

import asyncio
import logging
from typing import NamedTuple

import voluptuous as vol

from homeassistant.const import CONF_ENTITY_ID
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .const import (
    CONF_POWER_CYCLE_DELAY,
    DEFAULT_POWER_CYCLE_DELAY,
    DOMAIN,
    SERVICE_FACTORY_RESET,
    SERVICE_POWER_CYCLE,
)

_LOGGER = logging.getLogger(__name__)

CONF_DEVICE_ID = "device_id"
CONF_TOGGLE_COUNT = "toggle_count"
CONF_OFF_DURATION = "off_duration"
CONF_ON_DURATION = "on_duration"

# Power-cycling sequences for factory reset, keyed by manufacturer keyword
# (case-insensitive substring of device.manufacturer).
# Sequences are based on community documentation; exact timing may vary by
# firmware version and bulb model.
_RESET_SEQUENCES: dict[str, dict] = {
    # IKEA TRÅDFRI / Dirigera: 6 quick off/on cycles of ~2 s each
    "ikea": {"toggle_count": 6, "off_duration": 2.0, "on_duration": 2.0},
    # Philips Hue / Signify: 3 longer off/on cycles of ~5 s each
    "philips": {"toggle_count": 3, "off_duration": 5.0, "on_duration": 5.0},
    "signify": {"toggle_count": 3, "off_duration": 5.0, "on_duration": 5.0},
}
_RESET_SEQUENCE_DEFAULT = {"toggle_count": 6, "off_duration": 2.0, "on_duration": 2.0}

# entity_id and device_id are both optional; handlers validate that at least
# one resolves to a relay.  ALLOW_EXTRA lets area_id pass through without a
# schema error (we don't expand areas but we don't want to crash).
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


# ---------------------------------------------------------------------------
# Target resolution
# ---------------------------------------------------------------------------

class _RelayTarget(NamedTuple):
    relay: str
    light_entity_id: str | None  # None when targeting a switch directly


def _relay_for_light(hass: HomeAssistant, light_entity_id: str) -> str | None:
    """Return the relay entity_id paired with the given light, or None."""
    for data in hass.data.get(DOMAIN, {}).values():
        if isinstance(data, dict) and data.get("light") == light_entity_id:
            return data["relay"]
    return None


def _resolve_targets(hass: HomeAssistant, call_data: dict) -> list[_RelayTarget]:
    """Resolve entity_id / device_id from call data into (relay, light) pairs."""
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
        entity_reg = er.async_get(hass)
        for did in dids:
            found = False
            for entry in entity_reg.entities.values():
                if entry.device_id != did or entry.entity_id.split(".")[0] != "light":
                    continue
                relay = _relay_for_light(hass, entry.entity_id)
                if relay:
                    _add(relay, entry.entity_id)
                    found = True
            if not found:
                raise ServiceValidationError(
                    translation_domain=DOMAIN,
                    translation_key="no_relay_for_device",
                    translation_placeholders={"device_id": did},
                )

    return targets


# ---------------------------------------------------------------------------
# Manufacturer detection
# ---------------------------------------------------------------------------

def _reset_sequence_for_light(hass: HomeAssistant, light_entity_id: str) -> dict:
    """Return the factory-reset power sequence for the given light's manufacturer."""
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
# Power operations
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
    """Execute a factory-reset power sequence on relay_entity_id.

    Ensures the relay starts ON, then performs toggle_count off→on cycles.
    The relay is left ON at the end so the bulb can boot into reset mode.
    """
    _LOGGER.debug(
        "Factory reset on %s: %d toggles (off %.1fs / on %.1fs)",
        relay_entity_id, toggle_count, off_duration, on_duration,
    )
    # Guarantee starting state is on
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
# Service registration
# ---------------------------------------------------------------------------

async def async_register_services(hass: HomeAssistant) -> None:
    """Register integration services (idempotent)."""
    if hass.services.has_service(DOMAIN, SERVICE_POWER_CYCLE):
        return

    async def _handle_power_cycle(call: ServiceCall) -> None:
        delay: float = call.data.get(CONF_POWER_CYCLE_DELAY, DEFAULT_POWER_CYCLE_DELAY)
        targets = _resolve_targets(hass, call.data)
        if not targets:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="no_target_specified",
            )
        for t in targets:
            await _do_power_cycle(hass, t.relay, delay)

    async def _handle_factory_reset(call: ServiceCall) -> None:
        targets = _resolve_targets(hass, call.data)
        if not targets:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="no_target_specified",
            )
        for t in targets:
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

    hass.services.async_register(
        DOMAIN, SERVICE_POWER_CYCLE, _handle_power_cycle, schema=_POWER_CYCLE_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_FACTORY_RESET, _handle_factory_reset, schema=_FACTORY_RESET_SCHEMA
    )


def async_unregister_services(hass: HomeAssistant) -> None:
    """Remove services when the last config entry is unloaded."""
    if hass.data.get(DOMAIN):
        return
    for svc in (SERVICE_POWER_CYCLE, SERVICE_FACTORY_RESET):
        if hass.services.has_service(DOMAIN, svc):
            hass.services.async_remove(DOMAIN, svc)
