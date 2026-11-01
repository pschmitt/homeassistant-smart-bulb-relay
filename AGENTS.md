# Agent instructions

## Project

This Home Assistant integration pairs supported smart bulbs with Shelly relays and provides controls for power cycling, reset, status, and smart-mode behavior.

## Working in this repository

- Read `README.md` and `docs/shelly-watchdog.md` before changing pairing, MQTT heartbeat, or watchdog behavior.
- Keep relay and bulb control semantics consistent with the documented recovery and fallback behavior.
- Before changing CI, check [pschmitt/ci-workflows](https://github.com/pschmitt/ci-workflows) for reusable components and preserve this repository's existing checks.

## Validation

- Run `uvx ruff check .` and `uvx ruff format --check .` for Python changes.
- CI runs Hassfest and the shared Ruff checks; it currently has no test job.
