"""Constants for the Smart Bulb Relay integration."""

DOMAIN = "smart_bulb_relay"

CONF_RELAY_ENTITY_ID = "relay_entity_id"
CONF_LIGHT_ENTITY_ID = "light_entity_id"
CONF_POWER_CYCLE_DELAY = "power_cycle_delay"

DEFAULT_POWER_CYCLE_DELAY = 2.0  # seconds

SERVICE_POWER_CYCLE = "power_cycle"

# Manufacturer keywords used for auto-discovery (case-insensitive substring match).
SUPPORTED_LIGHT_MANUFACTURER_KEYWORDS = ("ikea", "philips", "signify")
