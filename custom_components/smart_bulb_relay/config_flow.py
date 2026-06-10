"""Config flow for Smart Bulb Relay."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.selector import (
    BooleanSelector,
    DeviceSelector,
    DeviceSelectorConfig,
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .const import (
    CONF_LIGHT_DEVICE_ID,
    CONF_LIGHT_ENTITY_ID,
    CONF_POWER_SENSOR_ENTITY_ID,
    CONF_POWER_THRESHOLD_W,
    CONF_RAISE_REPAIRS,
    CONF_RELAY_DEVICE_ID,
    CONF_RELAY_ENTITY_ID,
    CONF_SMART_MODE_ENABLED,
    DEFAULT_POWER_THRESHOLD_W,
    DEFAULT_RAISE_REPAIRS,
    DEFAULT_SMART_MODE_ENABLED,
    DOMAIN,
    SUPPORTED_LIGHT_MANUFACTURER_KEYWORDS,
)
from .registry import (
    discover_power_sensor,
    entry_light_device_id,
    entry_relay_device_id,
    resolve_device_entity,
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


def _relay_score(
    sw: er.RegistryEntry,
    lt: er.RegistryEntry,
    device_reg: dr.DeviceRegistry,
) -> int:
    """Word-overlap score between relay (entity + device name) and light name."""
    relay_words = _relay_meaningful_words(sw) | _meaningful_words(
        _device_name(sw, device_reg) or ""
    )
    light_words = _meaningful_words(_display_name(lt) + " " + lt.entity_id)
    return len(relay_words & light_words)


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
    5. Per-light deduplication: when multiple relays match the same light, only
       keep the relay(s) with the highest device-name-augmented overlap score.
       This prevents a generic "living room" relay from shadowing the more
       specific "living room table light" relay for the same IKEA bulb.
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
            and entry.entity_category is None
            and entry.device_id not in existing_relays
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

    # Per-light deduplication: keep only the relay(s) with the highest
    # device-name-augmented score for each light.  Ties (score == 0 included)
    # are preserved so the user can still choose in ambiguous situations.
    by_light: dict[str, list[tuple[er.RegistryEntry, er.RegistryEntry, int]]] = {}
    for sw, lt in candidates:
        score = _relay_score(sw, lt, device_reg)
        by_light.setdefault(lt.entity_id, []).append((sw, lt, score))

    deduped: list[tuple[er.RegistryEntry, er.RegistryEntry]] = []
    for group in by_light.values():
        best = max(s for _, _, s in group)
        if best > 0:
            deduped.extend((sw, lt) for sw, lt, s in group if s == best)
        else:
            deduped.extend((sw, lt) for sw, lt, _ in group)

    return deduped


# ---------------------------------------------------------------------------
# Config flow
# ---------------------------------------------------------------------------

class SmartBulbRelayConfigFlow(ConfigFlow, domain=DOMAIN):
    """Config flow for Smart Bulb Relay."""

    VERSION = 2

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> SmartBulbRelayOptionsFlow:
        return SmartBulbRelayOptionsFlow(config_entry)

    @property
    def _configured_relays(self) -> set[str]:
        return {
            device_id
            for e in self._async_current_entries()
            if (device_id := entry_relay_device_id(self.hass, e)) is not None
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
            selected: list[str] = user_input["pairing"]
            # Spawn a bulk flow for every pairing except the last one so we
            # can use async_create_entry (callable only once) for that one.
            for pairing in selected[:-1]:
                relay_device_id, light_device_id = pairing.split("|", 1)
                self.hass.async_create_task(
                    self.hass.config_entries.flow.async_init(
                        DOMAIN,
                        context={"source": "bulk"},
                        data={
                            CONF_RELAY_DEVICE_ID: relay_device_id,
                            CONF_LIGHT_DEVICE_ID: light_device_id,
                        },
                    )
                )
            relay_device_id, light_device_id = selected[-1].split("|", 1)
            return await self._async_create_entry(relay_device_id, light_device_id)

        options = [
            SelectOptionDict(
                value=f"{sw.device_id}|{lt.device_id}",
                label=_pairing_label(sw, lt, device_reg),
            )
            for sw, lt in candidates
            if sw.device_id and lt.device_id
        ]
        all_values = [o["value"] for o in options]
        return self.async_show_form(
            step_id="auto_discover",
            data_schema=vol.Schema(
                {
                    vol.Required("pairing", default=all_values): SelectSelector(
                        SelectSelectorConfig(
                            options=options,
                            mode=SelectSelectorMode.LIST,
                            multiple=True,
                        )
                    )
                }
            ),
        )

    async def async_step_bulk(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Programmatic entry point used when auto-discover creates multiple pairings at once."""
        if user_input is None:
            return self.async_abort(reason="already_configured")
        return await self._async_create_entry(
            user_input[CONF_RELAY_DEVICE_ID],
            user_input[CONF_LIGHT_DEVICE_ID],
        )

    async def async_step_manual(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return await self._async_create_entry(
                user_input[CONF_RELAY_DEVICE_ID],
                user_input[CONF_LIGHT_DEVICE_ID],
            )

        return self.async_show_form(
            step_id="manual",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_RELAY_DEVICE_ID): DeviceSelector(
                        DeviceSelectorConfig(integration="shelly")
                    ),
                    vol.Required(CONF_LIGHT_DEVICE_ID): DeviceSelector(
                        DeviceSelectorConfig(entity={"domain": "light"})
                    ),
                }
            ),
        )

    async def _async_create_entry(
        self, relay_device_id: str, light_device_id: str
    ) -> ConfigFlowResult:
        await self.async_set_unique_id(f"{relay_device_id}__{light_device_id}")
        self._abort_if_unique_id_configured()

        device_reg = dr.async_get(self.hass)
        title = light_device_id
        device = device_reg.async_get(light_device_id)
        if device:
            title = device.name_by_user or device.name or title

        relay_entity_id = resolve_device_entity(
            self.hass,
            relay_device_id,
            "switch",
            platform="shelly",
        )
        light_entity_id = resolve_device_entity(self.hass, light_device_id, "light")
        power_sensor_entity_id = discover_power_sensor(self.hass, relay_device_id)

        data: dict = {
            CONF_RELAY_DEVICE_ID: relay_device_id,
            CONF_LIGHT_DEVICE_ID: light_device_id,
            CONF_RELAY_ENTITY_ID: relay_entity_id,
            CONF_LIGHT_ENTITY_ID: light_entity_id,
        }
        options: dict = {}
        if power_sensor_entity_id:
            options[CONF_POWER_SENSOR_ENTITY_ID] = power_sensor_entity_id

        return self.async_create_entry(title=title, data=data, options=options)


# ---------------------------------------------------------------------------
# Options flow — edit an existing pairing
# ---------------------------------------------------------------------------

class SmartBulbRelayOptionsFlow(OptionsFlow):
    """Allow editing a relay/light pairing after initial setup."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        relay_device_id = entry_relay_device_id(self.hass, self._config_entry)
        current_smart_mode = self._config_entry.options.get(
            CONF_SMART_MODE_ENABLED, DEFAULT_SMART_MODE_ENABLED
        )
        current_raise_repairs = self._config_entry.options.get(
            CONF_RAISE_REPAIRS, DEFAULT_RAISE_REPAIRS
        )
        current_power_sensor = self._config_entry.options.get(
            CONF_POWER_SENSOR_ENTITY_ID
        )
        current_threshold = self._config_entry.options.get(
            CONF_POWER_THRESHOLD_W, DEFAULT_POWER_THRESHOLD_W
        )
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_RELAY_DEVICE_ID,
                        default=relay_device_id,
                    ): DeviceSelector(DeviceSelectorConfig(integration="shelly")),
                    vol.Required(
                        CONF_LIGHT_DEVICE_ID,
                        default=entry_light_device_id(self.hass, self._config_entry),
                    ): DeviceSelector(DeviceSelectorConfig(entity={"domain": "light"})),
                    vol.Optional(
                        CONF_SMART_MODE_ENABLED,
                        default=current_smart_mode,
                    ): BooleanSelector(),
                    vol.Optional(
                        CONF_RAISE_REPAIRS,
                        default=current_raise_repairs,
                    ): BooleanSelector(),
                    vol.Optional(
                        CONF_POWER_SENSOR_ENTITY_ID,
                        default=current_power_sensor,
                    ): EntitySelector(
                        EntitySelectorConfig(
                            domain="sensor",
                            device_class="power",
                        )
                    ),
                    vol.Optional(
                        CONF_POWER_THRESHOLD_W,
                        default=current_threshold,
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=0,
                            max=100,
                            step=0.1,
                            unit_of_measurement="W",
                            mode=NumberSelectorMode.BOX,
                        )
                    ),
                }
            ),
        )
