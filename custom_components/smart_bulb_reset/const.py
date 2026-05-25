"""Constants for the Smart Bulb Reset integration."""

DOMAIN = "smart_bulb_reset"

CONF_RELAY_ENTITY_ID = "relay_entity_id"
CONF_LIGHT_ENTITY_ID = "light_entity_id"
CONF_POWER_CYCLE_DELAY = "power_cycle_delay"
CONF_BRIGHTNESS_PCT = "brightness_pct"
CONF_COLOR_TEMP_KELVIN = "color_temp_kelvin"
CONF_LIGHT_CONTROL_TIMEOUT = "light_control_timeout"

DEFAULT_POWER_CYCLE_DELAY = 2.0       # seconds
DEFAULT_BRIGHTNESS_PCT = 85           # percent
DEFAULT_LIGHT_CONTROL_TIMEOUT = 1.0   # seconds

SERVICE_POWER_CYCLE = "power_cycle"
SERVICE_FACTORY_RESET = "factory_reset"
SERVICE_TURN_ON = "turn_on"
SERVICE_TURN_OFF = "turn_off"
SERVICE_TOGGLE = "toggle"

# Manufacturer keywords used for auto-discovery (case-insensitive substring match).
SUPPORTED_LIGHT_MANUFACTURER_KEYWORDS = ("ikea", "philips", "signify")
