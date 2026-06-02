# Smart Bulb Relay

A Home Assistant custom integration that pairs a **Shelly relay switch** with a **smart bulb** (IKEA Tradfri, Philips Hue) to give you the best of both worlds: a physical wall switch that always works, plus full smart-bulb control.

![Smart Bulb Relay](custom_components/smart_bulb_relay/icon.png)

## What it does

When a smart bulb is wired through a Shelly relay, the relay must stay on for the bulb to be reachable over Zigbee/Matter. This integration manages that relationship and exposes unified services and entities:

| Entity | Device | Description |
|--------|--------|-------------|
| `button.*_power_cycle` | Light | Power-cycles the relay (off → on) to wake an unresponsive bulb |
| `button.*_factory_reset` | Light | Triggers a factory reset via the manufacturer's toggle sequence |
| `switch.*_smart_mode` | Relay | When on: Shelly watchdog uses detached-input mode. When off: relay acts as a plain wall switch |
| `binary_sensor.*_bulb_status` | Light | `on` when the circuit draws more than the configured wattage threshold |

## Features

- **Auto-discovery** — scans your HA instance for Shelly switches and supported bulbs in the same area, matches them by name, and proposes pairings
- **Power cycle & factory reset** — one-click buttons on the light's device page; factory reset sequence auto-detected per manufacturer (IKEA: 6 × 2 s, Hue/Philips: 3 × 5 s)
- **Smart mode toggle** — exposes the Shelly `ha-watchdog` KVS flag as a switch; works alongside the [Shelly Detached Input blueprint](https://github.com/pschmitt/home-assistant-blueprints)
- **Smart Bulb Status sensor** — a `binary_sensor` backed by the relay's power sensor; tells you whether the bulb is drawing load regardless of its Zigbee availability
- **Smart turn on/off/toggle services** — prefer the light entity, fall back to the relay, power-cycle if the relay is already on but the bulb is unresponsive

## Supported bulbs

Auto-discovery matches bulbs from these manufacturers (case-insensitive substring match on the device manufacturer field):

- IKEA (Tradfri)
- Philips / Signify (Hue)

## Installation

### HACS (recommended)

1. Add this repository to HACS as a custom repository (Integration category).
2. Install **Smart Bulb Relay**.
3. Restart Home Assistant.

### Manual

```bash
cp -r custom_components/smart_bulb_relay \
  /config/custom_components/smart_bulb_relay
```

Restart Home Assistant.

## Configuration

Go to **Settings → Integrations → Add integration → Smart Bulb Relay**.

- **Auto-discover** — lets the integration find and propose all relay↔bulb pairings automatically.
- **Manual** — pick the Shelly device and the smart bulb device individually.

Each pairing creates its own config entry (one per relay/bulb pair). You can edit a pairing via the integration's **Configure** button to adjust:

| Option | Default | Description |
|--------|---------|-------------|
| Smart mode switch | enabled | Create the Smart Mode switch entity |
| Power sensor | auto-discovered | Sensor used to back the Smart Bulb Status binary sensor |
| Load threshold | 1 W | Wattage above which the Smart Bulb Status reports `on` |

## Blueprint

This integration works best with the companion [Shelly Detached Input](https://github.com/pschmitt/home-assistant-blueprints) blueprint, which handles wall-switch presses and uses both the Smart Mode switch and the Smart Bulb Status sensor to drive robust on/off/toggle logic.

## License

[GNU General Public License v3.0](LICENSE)
