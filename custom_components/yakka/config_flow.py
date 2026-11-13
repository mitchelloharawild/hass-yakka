"""Config flow for Yakka."""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import logging
from typing import Any

import voluptuous as vol

from homeassistant.components import webhook
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.network import NoURLAvailableError
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import YakkaAuthError, YakkaClient, YakkaConnectionError, YakkaError, parse_group_link
from .const import (
    CONF_BASE_URL,
    CONF_DEFAULT_MEMBER,
    CONF_GROUP_ID,
    CONF_GROUP_URL,
    CONF_MATCH_USERS,
    CONF_SCAN_INTERVAL,
    CONF_TOKEN,
    CONF_USER_MEMBERS,
    CONF_WEBHOOK_ID,
    CONF_WEBHOOK_SECRET,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_SCAN_INTERVAL_MINUTES,
    MIN_SCAN_INTERVAL_MINUTES,
    USE_DEFAULT_MEMBER,
)

_LOGGER = logging.getLogger(__name__)

CONF_ENABLE_WEBHOOK = "enable_webhook"
CONF_LINK_USERS = "link_users"
NO_MEMBER = "__automation__"
MATCH_BY_NAME = "__match__"

PASSWORD = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))
URL = TextSelector(TextSelectorConfig(type=TextSelectorType.URL))


def group_unique_id(base_url: str, group_id: str) -> str:
    """A stable id for a group that doesn't reveal its id.

    The group id is the group's access secret, so it isn't used directly in
    entity and device ids (which show up in logs and diagnostics).
    """
    return hashlib.sha256(f"{base_url.rstrip('/')}|{group_id}".encode()).hexdigest()[:16]


async def _validate(
    hass: HomeAssistant, link: str, token: str
) -> tuple[dict[str, str], dict[str, Any]]:
    """Check the link and token. Returns (errors, data)."""
    try:
        base_url, group_id = parse_group_link(link)
    except ValueError:
        return {CONF_GROUP_URL: "invalid_link"}, {}
    token = token.strip()
    client = YakkaClient(async_get_clientsession(hass), base_url, group_id, token)
    try:
        await client.get_members()
    except YakkaAuthError as err:
        return {"base": "group_mismatch" if err.status == 403 else "invalid_auth"}, {}
    except YakkaConnectionError:
        return {"base": "cannot_connect"}, {}
    except YakkaError as err:
        _LOGGER.debug("Yakka rejected the setup request: %s", err)
        return {"base": "not_yakka"}, {}
    except Exception:
        _LOGGER.exception("Unexpected error setting up Yakka")
        return {"base": "unknown"}, {}
    name = await client.get_group_name()
    return {}, {
        CONF_BASE_URL: base_url,
        CONF_GROUP_ID: group_id,
        CONF_TOKEN: token,
        "title": name or "Yakka",
    }


class YakkaConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up a Yakka group."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> YakkaOptionsFlow:
        """Options for an entry."""
        return YakkaOptionsFlow()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask for the group link and an API token."""
        errors: dict[str, str] = {}
        if user_input is not None:
            errors, data = await _validate(
                self.hass, user_input[CONF_GROUP_URL], user_input[CONF_TOKEN]
            )
            if not errors:
                await self.async_set_unique_id(
                    group_unique_id(data[CONF_BASE_URL], data[CONF_GROUP_ID])
                )
                self._abort_if_unique_id_configured()
                title = data.pop("title")
                return self.async_create_entry(title=title, data=data)
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(
                    {
                        vol.Required(CONF_GROUP_URL): URL,
                        vol.Required(CONF_TOKEN): PASSWORD,
                    }
                ),
                user_input,
            ),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """The token stopped working."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for a new token."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            link = f"{entry.data[CONF_BASE_URL]}/groups/{entry.data[CONF_GROUP_ID]}"
            errors, data = await _validate(self.hass, link, user_input[CONF_TOKEN])
            if not errors:
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_TOKEN: data[CONF_TOKEN]}
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_TOKEN): PASSWORD}),
            description_placeholders={"group": entry.title},
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Point the entry at a new address (e.g. the instance moved)."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            errors, data = await _validate(
                self.hass, user_input[CONF_GROUP_URL], user_input[CONF_TOKEN]
            )
            if not errors:
                data.pop("title")
                return self.async_update_reload_and_abort(entry, data_updates=data)
        current = {
            CONF_GROUP_URL: f"{entry.data[CONF_BASE_URL]}/groups/{entry.data[CONF_GROUP_ID]}"
        }
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(
                    {
                        vol.Required(CONF_GROUP_URL): URL,
                        vol.Required(CONF_TOKEN): PASSWORD,
                    }
                ),
                user_input or current,
            ),
            errors=errors,
        )


class YakkaOptionsFlow(OptionsFlow):
    """Default member, user matching, polling and webhook."""

    def __init__(self) -> None:
        """Initialise the flow."""
        self._options: dict[str, Any] = {}
        self._webhook_id: str | None = None
        self._enable_webhook = False
        # Form field name (the user's name) -> Home Assistant user id.
        self._user_fields: dict[str, str] = {}

    def _active_members(self) -> list[SelectOptionDict]:
        coordinator = getattr(self.config_entry, "runtime_data", None)
        if coordinator is None or coordinator.data is None:
            return []
        return [
            SelectOptionDict(value=m.id, label=m.name)
            for m in coordinator.data.members.values()
            if not m.archived
        ]

    async def _async_next(self) -> ConfigFlowResult:
        if self._enable_webhook:
            return await self.async_step_webhook()
        return self.async_create_entry(data=self._options)

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """General options."""
        options = self.config_entry.options
        if user_input is not None:
            self._enable_webhook = user_input.pop(CONF_ENABLE_WEBHOOK)
            link_users = user_input.pop(CONF_LINK_USERS)
            member = user_input.get(CONF_DEFAULT_MEMBER)
            if member in (None, NO_MEMBER):
                user_input.pop(CONF_DEFAULT_MEMBER, None)
            user_input[CONF_SCAN_INTERVAL] = int(user_input[CONF_SCAN_INTERVAL])
            self._options = user_input
            if link_users:
                return await self.async_step_users()
            return await self._async_next()

        member_options = [
            SelectOptionDict(value=NO_MEMBER, label="Automation"),
            *self._active_members(),
        ]
        default_minutes = int(DEFAULT_SCAN_INTERVAL.total_seconds() // 60)
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_DEFAULT_MEMBER,
                    default=options.get(CONF_DEFAULT_MEMBER, NO_MEMBER),
                ): SelectSelector(
                    SelectSelectorConfig(options=member_options, mode=SelectSelectorMode.DROPDOWN)
                ),
                vol.Required(
                    CONF_MATCH_USERS, default=options.get(CONF_MATCH_USERS, True)
                ): BooleanSelector(),
                vol.Required(
                    CONF_LINK_USERS,
                    default=bool(options.get(CONF_USER_MEMBERS)),
                ): BooleanSelector(),
                vol.Required(
                    CONF_SCAN_INTERVAL,
                    default=options.get(CONF_SCAN_INTERVAL, default_minutes),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=MIN_SCAN_INTERVAL_MINUTES,
                        max=MAX_SCAN_INTERVAL_MINUTES,
                        step=1,
                        unit_of_measurement="min",
                        mode=NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(
                    CONF_ENABLE_WEBHOOK,
                    default=bool(options.get(CONF_WEBHOOK_SECRET)),
                ): BooleanSelector(),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)

    async def async_step_users(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Choose the Yakka member for each Home Assistant user."""
        if user_input is not None:
            links = {
                self._user_fields[field]: choice
                for field, choice in user_input.items()
                if field in self._user_fields and choice != MATCH_BY_NAME
            }
            if links:
                self._options[CONF_USER_MEMBERS] = links
            return await self._async_next()

        users = sorted(
            (
                u
                for u in await self.hass.auth.async_get_users()
                if u.is_active and not u.system_generated
            ),
            key=lambda u: (u.name or "").casefold(),
        )
        # Fields are named after the users so the form reads naturally.
        self._user_fields = {}
        for user in users:
            base = (user.name or "").strip() or user.id
            field, n = base, 2
            while field in self._user_fields:
                field, n = f"{base} ({n})", n + 1
            self._user_fields[field] = user.id

        members = self._active_members()
        choices = [
            SelectOptionDict(value=MATCH_BY_NAME, label="Match by name"),
            SelectOptionDict(value=USE_DEFAULT_MEMBER, label="Record as the default"),
            *members,
        ]
        valid = {c["value"] for c in choices}
        links = self.config_entry.options.get(CONF_USER_MEMBERS, {})
        selector = SelectSelector(
            SelectSelectorConfig(options=choices, mode=SelectSelectorMode.DROPDOWN)
        )
        schema = vol.Schema(
            {
                vol.Required(
                    field,
                    default=(links[user_id] if links.get(user_id) in valid else MATCH_BY_NAME),
                ): selector
                for field, user_id in self._user_fields.items()
            }
        )
        return self.async_show_form(step_id="users", data_schema=schema)

    async def async_step_webhook(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the webhook URL to paste into Yakka and take its signing secret."""
        options = self.config_entry.options
        if self._webhook_id is None:
            # Keep the same id across re-shows of the form, and across edits.
            self._webhook_id = options.get(CONF_WEBHOOK_ID) or webhook.async_generate_id()
        webhook_id = self._webhook_id
        errors: dict[str, str] = {}
        if user_input is not None:
            secret = user_input[CONF_WEBHOOK_SECRET].strip()
            if not secret.startswith("whsec_"):
                errors[CONF_WEBHOOK_SECRET] = "invalid_secret"
            else:
                return self.async_create_entry(
                    data={
                        **self._options,
                        CONF_WEBHOOK_ID: webhook_id,
                        CONF_WEBHOOK_SECRET: secret,
                    }
                )
        try:
            url = webhook.async_generate_url(self.hass, webhook_id)
        except NoURLAvailableError:
            url = webhook.async_generate_path(webhook_id)
        return self.async_show_form(
            step_id="webhook",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema({vol.Required(CONF_WEBHOOK_SECRET): PASSWORD}),
                {CONF_WEBHOOK_SECRET: options.get(CONF_WEBHOOK_SECRET, "")},
            ),
            description_placeholders={"webhook_url": url},
            errors=errors,
        )
