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
# {Home Assistant user id: Yakka member id, or USE_DEFAULT_MEMBER}
CONF_USER_MEMBERS: Final = "user_members"
CONF_WEBHOOK_ID: Final = "webhook_id"
CONF_WEBHOOK_SECRET: Final = "webhook_secret"

# A user linked to this records as the default member, never matched by name.
USE_DEFAULT_MEMBER: Final = "__default__"

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
# Statuses that mean "there is something to do now".
ACTIONABLE_STATUSES: Final = frozenset({STATUS_DUE, STATUS_OVERDUE})

# Event fired on the Home Assistant bus for every verified Yakka webhook.
EVENT_YAKKA: Final = "yakka_event"

# Services
SERVICE_COMPLETE_CHORE: Final = "complete_chore"
SERVICE_UNDO_COMPLETION: Final = "undo_completion"
ATTR_CONFIG_ENTRY_ID: Final = "config_entry_id"
ATTR_CHORE: Final = "chore"
ATTR_MEMBER: Final = "member"
ATTR_NOTE: Final = "note"
ATTR_COMPLETED_AT: Final = "completed_at"
ATTR_COMPLETION_ID: Final = "completion_id"
