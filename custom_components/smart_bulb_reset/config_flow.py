"""Config flow for Smart Bulb Reset."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .const import (
    CONF_LIGHT_ENTITY_ID,
    CONF_RELAY_ENTITY_ID,
    DOMAIN,
    SUPPORTED_LIGHT_MANUFACTURER_KEYWORDS,
)

_LOGGER = logging.getLogger(__name__)

# Switch name/entity_id must contain one of these for auto-discovery to consider
# it a light relay (case-insensitive substring match across name + entity_id).
_RELAY_NAME_KEYWORDS = (
    "light", "lamp", "ceiling", "bulb", "led", "spot",
    "licht", "leuchte", "lampe",
)


# ---------------------------------------------------------------------------
# Discovery helpers
# ---------------------------------------------------------------------------

def _entity_area_id(
    entry: er.RegistryEntry, device_reg: dr.DeviceRegistry
) -> str | None:
    """Return effective area_id (entity override → device fallback)."""
    if entry.area_id:
        return entry.area_id
    if entry.device_id:
        device = device_reg.async_get(entry.device_id)
        if device:
            return device.area_id
    return None


def _is_supported_light(
    entry: er.RegistryEntry, device_reg: dr.DeviceRegistry
) -> bool:
    """Return True if the light belongs to a supported manufacturer (IKEA/Hue)."""
    if not entry.device_id:
        return False
    device = device_reg.async_get(entry.device_id)
    if not device or not device.manufacturer:
        return False
    m = device.manufacturer.lower()
    return any(kw in m for kw in SUPPORTED_LIGHT_MANUFACTURER_KEYWORDS)


_NON_RELAY_TOKENS = frozenset({"ble", "bluetooth"})

# Lights whose names contain these words are secondary/accent fixtures that
# are almost never wired through a relay (bedside tables, wardrobes, etc.).
_SECONDARY_LIGHT_TOKENS = frozenset({
    "bedside", "wardrobe", "couch", "sofa", "nightstand", "closet",
})

# Words ignored when computing relay↔light name overlap.
_NAME_STOPWORDS = frozenset({
    "light", "lights", "lamp", "switch", "shelly", "hue", "ikea",
    "tradfri", "the", "a", "an", "of", "in", "for", "and", "or",
})


def _tokenise(text: str) -> set[str]:
    return set(text.lower().replace(".", " ").replace("_", " ").split())


def _meaningful_words(text: str) -> set[str]:
    return _tokenise(text) - _NAME_STOPWORDS


def _looks_like_light_relay(entry: er.RegistryEntry) -> bool:
    """Return True if the switch's own name/entity_id suggests it controls a light circuit.

    Checks only entity-level identifiers (entity_id, name, original_name) —
    NOT the device name, which is shared by all entities on the device and
    would cause secondary entities (e.g. BLE proxy) to inherit it.

    Entities whose tokenised identifiers contain "ble" or "bluetooth" are
    excluded even if they pass the keyword test, because Shelly BLE proxy
    entities get entity_ids like switch.office_light_aioshelly_ble_integration
    where "light" comes from the device-name prefix.
    """
    parts = [entry.entity_id]
    if entry.name:
        parts.append(entry.name)
    if entry.original_name:
        parts.append(entry.original_name)
    combined = " ".join(parts).lower()
    tokens = _tokenise(combined)
    if tokens & _NON_RELAY_TOKENS:
        return False
    return any(kw in combined for kw in _RELAY_NAME_KEYWORDS)


def _is_secondary_light(entry: er.RegistryEntry) -> bool:
    """Return True if the light name suggests a secondary/accent fixture."""
    combined = " ".join(filter(None, [entry.name, entry.original_name, entry.entity_id]))
    return bool(_tokenise(combined) & _SECONDARY_LIGHT_TOKENS)


def _relay_meaningful_words(entry: er.RegistryEntry) -> set[str]:
    """Meaningful words from the relay's name, falling back to its entity_id."""
    parts = [entry.entity_id]
    if entry.name:
        parts.append(entry.name)
    if entry.original_name:
        parts.append(entry.original_name)
    return _meaningful_words(" ".join(parts))


def _display_name(entry: er.RegistryEntry) -> str:
    return entry.name or entry.original_name or entry.entity_id


def _device_name(entry: er.RegistryEntry, device_reg: dr.DeviceRegistry) -> str | None:
    if not entry.device_id:
        return None
    device = device_reg.async_get(entry.device_id)
    return device.name_by_user or device.name if device else None


def _pairing_label(
    sw: er.RegistryEntry,
    lt: er.RegistryEntry,
    device_reg: dr.DeviceRegistry,
) -> str:
    sw_dev = _device_name(sw, device_reg)
    lt_dev = _device_name(lt, device_reg)
    relay_part = f"{sw_dev} ({sw.entity_id})" if sw_dev else sw.entity_id
    light_part = f"{lt_dev} ({lt.entity_id})" if lt_dev else lt.entity_id
    return f"{relay_part} → {light_part}"


def _discover_candidates(
    entity_reg: er.EntityRegistry,
    device_reg: dr.DeviceRegistry,
    existing_relays: set[str],
) -> list[tuple[er.RegistryEntry, er.RegistryEntry]]:
    """Return area-matched (relay_switch, smart_light) pairs not yet configured.

    Filtering pipeline:
    1. Relay must be a Shelly switch whose own name/entity_id contains a
       light-related keyword (rules out appliance sockets) and no BLE tokens.
    2. Light must be an IKEA or Hue device.
    3. Light must not be a secondary fixture (bedside, wardrobe, couch …).
    4. Relay and light must share at least one meaningful name word. If a
       relay has no meaningful words (e.g. named just "Light") OR no light
       in the area survives the overlap test, all primary lights in the area
       are offered as a fallback.
    """
    shelly_switches: list[er.RegistryEntry] = []
    primary_lights: list[er.RegistryEntry] = []

    for entry in entity_reg.entities.values():
        if entry.disabled_by:
            continue
        entity_domain = entry.entity_id.split(".")[0]
        if (
            entity_domain == "switch"
            and entry.platform == "shelly"
            and entry.entity_id not in existing_relays
            and _looks_like_light_relay(entry)
        ):
            shelly_switches.append(entry)
        elif (
            entity_domain == "light"
            and _is_supported_light(entry, device_reg)
            and not _is_secondary_light(entry)
        ):
            primary_lights.append(entry)

    lights_by_area: dict[str, list[er.RegistryEntry]] = {}
    for light in primary_lights:
        area_id = _entity_area_id(light, device_reg)
        if area_id:
            lights_by_area.setdefault(area_id, []).append(light)

    candidates: list[tuple[er.RegistryEntry, er.RegistryEntry]] = []
    for switch in shelly_switches:
        area_id = _entity_area_id(switch, device_reg)
        if not area_id or area_id not in lights_by_area:
            continue
        area_lights = lights_by_area[area_id]
        relay_words = _relay_meaningful_words(switch)
        if relay_words:
            matched = [
                lt for lt in area_lights
                if relay_words & _meaningful_words(_display_name(lt) + " " + lt.entity_id)
            ]
            area_lights = matched or area_lights  # fallback if nothing overlaps
        for light in area_lights:
            candidates.append((switch, light))

    return candidates


# ---------------------------------------------------------------------------
# Config flow
# ---------------------------------------------------------------------------

class SmartBulbResetConfigFlow(ConfigFlow, domain=DOMAIN):
    """Config flow for Smart Bulb Reset."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> SmartBulbResetOptionsFlow:
        return SmartBulbResetOptionsFlow(config_entry)

    @property
    def _configured_relays(self) -> set[str]:
        return {
            e.data[CONF_RELAY_ENTITY_ID]
            for e in self._async_current_entries()
            if CONF_RELAY_ENTITY_ID in e.data
        }

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            if user_input["setup_type"] == "auto":
                return await self.async_step_auto_discover()
            return await self.async_step_manual()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required("setup_type", default="auto"): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                SelectOptionDict(value="auto", label="Auto-discover"),
                                SelectOptionDict(value="manual", label="Manual"),
                            ],
                            mode=SelectSelectorMode.LIST,
                        )
                    )
                }
            ),
        )

    async def async_step_auto_discover(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entity_reg = er.async_get(self.hass)
        device_reg = dr.async_get(self.hass)
        candidates = _discover_candidates(entity_reg, device_reg, self._configured_relays)

        if not candidates:
            _LOGGER.debug(
                "Auto-discover: no candidates after keyword filtering; falling back to manual"
            )
            return await self.async_step_manual()

        if user_input is not None:
            relay_id, light_id = user_input["pairing"].split("|", 1)
            return await self._async_create_entry(relay_id, light_id)

        options = [
            SelectOptionDict(
                value=f"{sw.entity_id}|{lt.entity_id}",
                label=_pairing_label(sw, lt, device_reg),
            )
            for sw, lt in candidates
        ]
        return self.async_show_form(
            step_id="auto_discover",
            data_schema=vol.Schema(
                {
                    vol.Required("pairing"): SelectSelector(
                        SelectSelectorConfig(options=options, mode=SelectSelectorMode.LIST)
                    )
                }
            ),
        )

    async def async_step_manual(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return await self._async_create_entry(
                user_input[CONF_RELAY_ENTITY_ID],
                user_input[CONF_LIGHT_ENTITY_ID],
            )

        return self.async_show_form(
            step_id="manual",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_RELAY_ENTITY_ID): EntitySelector(
                        EntitySelectorConfig(domain="switch")
                    ),
                    vol.Required(CONF_LIGHT_ENTITY_ID): EntitySelector(
                        EntitySelectorConfig(domain="light")
                    ),
                }
            ),
        )

    async def _async_create_entry(
        self, relay_entity_id: str, light_entity_id: str
    ) -> ConfigFlowResult:
        await self.async_set_unique_id(f"{relay_entity_id}__{light_entity_id}")
        self._abort_if_unique_id_configured()

        entity_reg = er.async_get(self.hass)
        light_entry = entity_reg.async_get(light_entity_id)
        title = _display_name(light_entry) if light_entry else light_entity_id

        return self.async_create_entry(
            title=title,
            data={
                CONF_RELAY_ENTITY_ID: relay_entity_id,
                CONF_LIGHT_ENTITY_ID: light_entity_id,
            },
        )


# ---------------------------------------------------------------------------
# Options flow — edit an existing pairing
# ---------------------------------------------------------------------------

class SmartBulbResetOptionsFlow(OptionsFlow):
    """Allow editing a relay/light pairing after initial setup."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        self._config_entry = config_entry

    def _current(self, key: str) -> str:
        """Return effective value for key (options override data)."""
        return self._config_entry.options.get(key) or self._config_entry.data[key]

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_RELAY_ENTITY_ID,
                        default=self._current(CONF_RELAY_ENTITY_ID),
                    ): EntitySelector(EntitySelectorConfig(domain="switch")),
                    vol.Required(
                        CONF_LIGHT_ENTITY_ID,
                        default=self._current(CONF_LIGHT_ENTITY_ID),
                    ): EntitySelector(EntitySelectorConfig(domain="light")),
                }
            ),
        )
