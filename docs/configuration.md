# Pairing and controls

A Shelly relay supplies mains power to a smart bulb. The integration can
propose pairings between Shelly switches and IKEA Tradfri or Philips/Signify
Hue bulbs in the same Home Assistant area, matching by name. You can instead
select a Shelly and bulb manually. Each pairing is a separate config entry.

Its device entities include:

| Entity | Purpose |
|--------|---------|
| `button.*_power_cycle` | Cycle relay power to recover an unresponsive bulb |
| `button.*_factory_reset` | Use the bulb manufacturer's toggle sequence |
| `switch.*_smart_mode` | Request detached input and Shelly watchdog operation |
| `binary_sensor.*_bulb_status` | Report whether relay power draw exceeds a threshold |

The reset sequence is selected by bulb manufacturer (IKEA: six 2-second
cycles; Hue/Philips: three 5-second cycles). The smart turn-on, turn-off and
toggle services prefer the light entity and fall back to the relay, cycling
power when the relay is already on but the light is unresponsive.

Under the pairing's **Configure** button, choose whether to create the Smart
Mode switch, which power sensor to use (auto-discovered by default) and the
load threshold (default 1 W).

The companion [Shelly Detached Input blueprint](https://github.com/pschmitt/home-assistant-blueprints)
handles wall-switch presses. MQTT must be configured on both Home Assistant
and each Shelly for watchdog operation; see [Shelly watchdog](shelly-watchdog.md)
for input ownership, heartbeats, fallback and recovery.
