"""Repairs watcher and fix flow for Smart Bulb Relay.

Raises a HA Repairs issue when a managed light is unreachable for 5 minutes,
and clears it automatically when the device comes back.
The issue is fixable: clicking "Fix Issue" offers a one-click power cycle.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from homeassistant.components.repairs import RepairsFlow
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED, STATE_UNAVAILABLE
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.event import async_call_later, async_track_state_change_event

from .const import DOMAIN, SERVICE_POWER_CYCLE

_ISSUE_PREFIX = "light_unreachable"

_LOGGER = logging.getLogger(__name__)

_UNREACHABLE_DELAY_S = 5 * 60  # seconds — matches the automation's for: 00:05:00


class BulbReachabilityWatcher:
    """Watch a light entity and raise/clear a Repairs issue when it is unreachable."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        light_entity_id: str,
        light_name: str,
    ) -> None:
        self._hass = hass
        self._entry = entry
        self._light_entity_id = light_entity_id
        self._light_name = light_name
        self._issue_id = f"light_unreachable_{entry.entry_id}"
        self._cancel_timer: Callable | None = None
        self._unsubscribe: Callable | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start watching; schedule startup check once HA is fully up."""
        self._unsubscribe = async_track_state_change_event(
            self._hass,
            [self._light_entity_id],
            self._on_state_change,
        )

        if self._hass.is_running:
            # Integration reloaded while HA is up — check immediately.
            self._check_current_state()
        else:
            # HA startup path — wait until all integrations are loaded so
            # ZHA has had a chance to mark the device reachable/unreachable.
            @callback
            def _on_ha_started(_event: Event) -> None:
                self._check_current_state()

            self._entry.async_on_unload(
                self._hass.bus.async_listen_once(
                    EVENT_HOMEASSISTANT_STARTED, _on_ha_started
                )
            )

    def stop(self) -> None:
        """Stop watching and clear any pending state."""
        if self._unsubscribe:
            self._unsubscribe()
            self._unsubscribe = None
        self._cancel_pending_timer()
        ir.async_delete_issue(self._hass, DOMAIN, self._issue_id)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @callback
    def _check_current_state(self) -> None:
        state = self._hass.states.get(self._light_entity_id)
        if state and state.state == STATE_UNAVAILABLE:
            self._schedule_issue()

    @callback
    def _on_state_change(self, event: Event) -> None:
        new_state = event.data.get("new_state")
        if new_state is None:
            return
        if new_state.state == STATE_UNAVAILABLE:
            self._schedule_issue()
        else:
            self._cancel_pending_timer()
            ir.async_delete_issue(self._hass, DOMAIN, self._issue_id)

    def _schedule_issue(self) -> None:
        if self._cancel_timer is not None:
            return  # timer already running

        @callback
        def _raise(_now) -> None:  # noqa: ANN001
            self._cancel_timer = None
            _LOGGER.debug(
                "Raising repair issue for %s (unreachable for %ds)",
                self._light_entity_id,
                _UNREACHABLE_DELAY_S,
            )
            self._create_issue()

        self._cancel_timer = async_call_later(
            self._hass, _UNREACHABLE_DELAY_S, _raise
        )

    def _cancel_pending_timer(self) -> None:
        if self._cancel_timer is not None:
            self._cancel_timer()
            self._cancel_timer = None

    def _create_issue(self) -> None:
        ir.async_create_issue(
            self._hass,
            DOMAIN,
            self._issue_id,
            is_fixable=True,
            severity=ir.IssueSeverity.WARNING,
            translation_key="light_unreachable",
            translation_placeholders={"light_name": self._light_name},
        )


# ---------------------------------------------------------------------------
# Fix flow
# ---------------------------------------------------------------------------

async def async_create_fix_flow(
    hass: HomeAssistant,
    issue_id: str,
    data: dict[str, Any] | None,
) -> RepairsFlow:
    """Return the appropriate repair flow for the given issue."""
    if issue_id.startswith(_ISSUE_PREFIX):
        entry_id = issue_id[len(_ISSUE_PREFIX) + 1:]  # strip "light_unreachable_"
        return PowerCycleRepairFlow(entry_id)
    raise ValueError(f"Unknown issue_id: {issue_id}")


class PowerCycleRepairFlow(RepairsFlow):
    """One-step repair flow: confirm → power cycle the relay."""

    def __init__(self, entry_id: str) -> None:
        self._entry_id = entry_id

    @property
    def _light_name(self) -> str:
        entry = self.hass.config_entries.async_get_entry(self._entry_id)
        return entry.title if entry else self._entry_id

    @property
    def _light_entity_id(self) -> str | None:
        return self.hass.data.get(DOMAIN, {}).get(self._entry_id, {}).get("light")

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None:
            light = self._light_entity_id
            if light:
                await self.hass.services.async_call(
                    DOMAIN,
                    SERVICE_POWER_CYCLE,
                    {"entity_id": light},
                    blocking=False,
                )
            return self.async_create_entry(data={})

        return self.async_show_form(
            step_id="init",
            description_placeholders={"light_name": self._light_name},
        )
