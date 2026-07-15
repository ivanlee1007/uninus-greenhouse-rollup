"""Constants for the UNiNUS greenhouse roll-up integration."""

DOMAIN = "uninus_greenhouse_rollup"
PLATFORMS = ["cover"]

CONF_OPEN_ENTITY = "open_entity"
CONF_CLOSE_ENTITY = "close_entity"
CONF_OPEN_TRAVEL_TIME = "open_travel_time"
CONF_CLOSE_TRAVEL_TIME = "close_travel_time"
CONF_REVERSE_DEAD_TIME = "reverse_dead_time"

DEFAULT_OPEN_TRAVEL_TIME = 120
DEFAULT_CLOSE_TRAVEL_TIME = 120
DEFAULT_REVERSE_DEAD_TIME = 0.2
CARD_URL = "/uninus-greenhouse-rollup/uninus-greenhouse-rollup-card.js"
