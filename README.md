<p align="center">
  <img src="custom_components/smart_bulb_relay/icon.png" width="96" alt="Smart Bulb Relay icon">
</p>

<p align="center">
  <a href="https://my.home-assistant.io/redirect/marketplace_repository/?owner=pschmitt&amp;repository=homeassistant-smart-bulb-relay&amp;category=integration"><img src="https://my.home-assistant.io/badges/marketplace_repository.svg" alt="Open this integration in Home Assistant Marketplace"></a>
</p>

<h1 align="center">Smart Bulb Relay</h1>

<p align="center">Pair a Shelly wall-switch relay with a smart bulb and keep local control when Home Assistant is unavailable.</p>

## Features

- **Pairing:** Discover or manually pair a Shelly relay with an IKEA or Hue bulb. See [Pairing and controls](docs/configuration.md).
- **Bulb recovery:** Offer power-cycle and manufacturer-specific factory-reset buttons.
- **Smart controls:** Use the light when available and fall back to the relay; estimate bulb status from power draw.
- **Local fallback:** Send MQTT heartbeats to a Shelly watchdog that returns input control to the device during outages. See [Shelly watchdog](docs/shelly-watchdog.md).

## Install

Use the Marketplace badge above on Home Assistant 2026.11 or later to add this
repository as a custom integration. On older versions, add it as a HACS
custom repository of type **Integration**. Install and restart Home Assistant.
The badge does not imply a public catalog listing. For manual installation,
copy `custom_components/smart_bulb_relay/` into Home Assistant's
`custom_components/` directory and restart.

## Quick start

1. Add **Smart Bulb Relay** under **Settings → Devices & services → Add integration**.
2. Choose auto-discovery or manually pair a Shelly relay and smart bulb.
3. Set up the companion [Shelly Detached Input blueprint](https://github.com/pschmitt/home-assistant-blueprints) for wall-switch control.
4. Configure MQTT on Home Assistant and the Shelly to use watchdog fallback.

## Documentation

| Topic | Description |
|-------|-------------|
| [Pairing and controls](docs/configuration.md) | Pairing choices, entities and settings |
| [Shelly watchdog](docs/shelly-watchdog.md) | Input ownership, heartbeat, fallback and troubleshooting |

## License

[GPL-3.0](LICENSE).
