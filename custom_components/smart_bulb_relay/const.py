"""Constants for the Smart Bulb Relay integration."""

DOMAIN = "smart_bulb_relay"

CONF_RELAY_ENTITY_ID = "relay_entity_id"
CONF_LIGHT_ENTITY_ID = "light_entity_id"
CONF_RELAY_DEVICE_ID = "relay_device_id"
CONF_LIGHT_DEVICE_ID = "light_device_id"
CONF_POWER_CYCLE_DELAY = "power_cycle_delay"
CONF_BRIGHTNESS_PCT = "brightness_pct"
CONF_COLOR_TEMP_KELVIN = "color_temp_kelvin"
CONF_LIGHT_CONTROL_TIMEOUT = "light_control_timeout"
CONF_SMART_MODE_ENABLED = "smart_mode_enabled"
CONF_POWER_SENSOR_ENTITY_ID = "power_sensor_entity_id"
CONF_POWER_THRESHOLD_W = "power_threshold_w"

CONF_RAISE_REPAIRS = "raise_repairs"

DEFAULT_POWER_CYCLE_DELAY = 2.0       # seconds
DEFAULT_BRIGHTNESS_PCT = 85           # percent
DEFAULT_LIGHT_CONTROL_TIMEOUT = 1.0   # seconds
DEFAULT_SMART_MODE_ENABLED = True
DEFAULT_RAISE_REPAIRS = True
DEFAULT_POWER_THRESHOLD_W = 0.6       # watts

SHELLY_WATCHDOG_FORCE_FALLBACK_KEY = "ha-watchdog-force-fallback"

SERVICE_POWER_CYCLE = "power_cycle"
SERVICE_FACTORY_RESET = "factory_reset"
SERVICE_TURN_ON = "turn_on"
SERVICE_TURN_OFF = "turn_off"
SERVICE_TOGGLE = "toggle"
SERVICE_MAKE_ALL_DUMB = "make_all_dumb"
SERVICE_MAKE_ALL_SMART = "make_all_smart"

# Manufacturer keywords used for auto-discovery (case-insensitive substring match).
SUPPORTED_LIGHT_MANUFACTURER_KEYWORDS = ("ikea", "philips", "signify")
