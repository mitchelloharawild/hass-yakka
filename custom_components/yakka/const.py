"""Constants for the Yakka integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "yakka"

CONF_BASE_URL: Final = "base_url"
CONF_GROUP_ID: Final = "group_id"
CONF_GROUP_URL: Final = "group_url"
CONF_TOKEN: Final = "token"

# Options
CONF_DEFAULT_MEMBER: Final = "default_member"
CONF_MATCH_USERS: Final = "match_users"
CONF_SCAN_INTERVAL: Final = "scan_interval"

DEFAULT_SCAN_INTERVAL: Final = timedelta(minutes=5)
MIN_SCAN_INTERVAL_MINUTES: Final = 1
MAX_SCAN_INTERVAL_MINUTES: Final = 1440

# Chore statuses reported by the API.
STATUS_UPCOMING: Final = "upcoming"
STATUS_DUE: Final = "due"
STATUS_OVERDUE: Final = "overdue"
STATUS_DONE: Final = "done"
STATUS_UNSCHEDULED: Final = "unscheduled"
STATUSES: Final = [
    STATUS_UPCOMING,
    STATUS_DUE,
    STATUS_OVERDUE,
    STATUS_DONE,
    STATUS_UNSCHEDULED,
]
