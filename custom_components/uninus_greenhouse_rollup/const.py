"""Constants for the UNiNUS greenhouse roll-up integration."""

DOMAIN = "uninus_greenhouse_rollup"
PLATFORMS = ["cover"]

CONF_ACTUATOR_MODE = "actuator_mode"
ACTUATOR_MODE_DUAL_SWITCH = "dual_switch"
ACTUATOR_MODE_NATIVE_COVER = "native_cover"

CONF_OPEN_ENTITY = "open_entity"
CONF_CLOSE_ENTITY = "close_entity"
CONF_OPEN_TRAVEL_TIME = "open_travel_time"
CONF_CLOSE_TRAVEL_TIME = "close_travel_time"
CONF_REVERSE_DEAD_TIME = "reverse_dead_time"
CONF_AUTO_STOP_AT_TRAVEL_END = "auto_stop_at_travel_end"

DEFAULT_OPEN_TRAVEL_TIME = 120
DEFAULT_CLOSE_TRAVEL_TIME = 120
DEFAULT_REVERSE_DEAD_TIME = 0.2
DEFAULT_AUTO_STOP_AT_TRAVEL_END = False
