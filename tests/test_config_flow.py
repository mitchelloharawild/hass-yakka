"""Config and options flow tests."""

from __future__ import annotations

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from .fixtures import GROUP_ID, TOKEN
from .helpers import API, BASE, make_entry, mock_api
from custom_components.yakka.const import (
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
    DOMAIN,
    USE_DEFAULT_MEMBER,
)


async def test_user_flow(hass: HomeAssistant, aioclient_mock) -> None:
    mock_api(aioclient_mock)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_GROUP_URL: f"{BASE}/groups/{GROUP_ID}/integrations", CONF_TOKEN: f" {TOKEN} "},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Home"
    assert result["data"] == {CONF_BASE_URL: BASE, CONF_GROUP_ID: GROUP_ID, CONF_TOKEN: TOKEN}

    # The same group again is refused.
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_GROUP_URL: f"{BASE}/groups/{GROUP_ID}", CONF_TOKEN: TOKEN}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_user_flow_errors(hass: HomeAssistant, aioclient_mock) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_GROUP_URL: "https://yakka.example/", CONF_TOKEN: TOKEN}
    )
    assert result["errors"] == {CONF_GROUP_URL: "invalid_link"}

    aioclient_mock.get(
        f"{API}/members",
        status=403,
        json={"error": {"code": "TOKEN_GROUP_MISMATCH", "message": "other group"}},
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_GROUP_URL: f"{BASE}/groups/{GROUP_ID}", CONF_TOKEN: TOKEN}
    )
    assert result["errors"] == {"base": "group_mismatch"}


async def test_reauth(hass: HomeAssistant, aioclient_mock) -> None:
    mock_api(aioclient_mock)
    entry = make_entry()
    entry.add_to_hass(hass)
    result = await entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_TOKEN: "yk_new"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_TOKEN] == "yk_new"


async def test_options_with_webhook(hass: HomeAssistant, aioclient_mock) -> None:
    mock_api(aioclient_mock)
    entry = make_entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["step_id"] == "init"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_DEFAULT_MEMBER: "m2",
            CONF_MATCH_USERS: False,
            CONF_SCAN_INTERVAL: 10,
            "link_users": False,
            "enable_webhook": True,
        },
    )
    assert result["step_id"] == "webhook"
    url = result["description_placeholders"]["webhook_url"]

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_WEBHOOK_SECRET: "nope"}
    )
    assert result["errors"] == {CONF_WEBHOOK_SECRET: "invalid_secret"}
    assert result["description_placeholders"]["webhook_url"] == url  # same id on retry

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_WEBHOOK_SECRET: "whsec_abc"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_DEFAULT_MEMBER] == "m2"
    assert entry.options[CONF_SCAN_INTERVAL] == 10
    assert entry.options[CONF_WEBHOOK_SECRET] == "whsec_abc"
    assert url.endswith(entry.options[CONF_WEBHOOK_ID])


async def test_options_link_users(
    hass: HomeAssistant, aioclient_mock, hass_admin_user, hass_read_only_user
) -> None:
    await hass.auth.async_update_user(hass_admin_user, name="Pat")
    await hass.auth.async_update_user(hass_read_only_user, name="Pat")
    mock_api(aioclient_mock)
    entry = make_entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_DEFAULT_MEMBER: "__automation__",
            CONF_MATCH_USERS: True,
            CONF_SCAN_INTERVAL: 5,
            "link_users": True,
            "enable_webhook": False,
        },
    )
    assert result["step_id"] == "users"
    # One field per user, named after them; a repeated name gets a suffix.
    assert {str(key) for key in result["data_schema"].schema} == {"Pat", "Pat (2)"}

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {"Pat": "m2", "Pat (2)": USE_DEFAULT_MEMBER},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert sorted(entry.options[CONF_USER_MEMBERS].values()) == [USE_DEFAULT_MEMBER, "m2"]
    assert set(entry.options[CONF_USER_MEMBERS]) == {
        hass_admin_user.id,
        hass_read_only_user.id,
    }
    assert CONF_DEFAULT_MEMBER not in entry.options

    # The links are shown again next time, and turning the switch off clears them.
    result = await hass.config_entries.options.async_init(entry.entry_id)
    schema = result["data_schema"].schema
    assert next(k for k in schema if k == "link_users").default() is True
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_DEFAULT_MEMBER: "__automation__",
            CONF_MATCH_USERS: True,
            CONF_SCAN_INTERVAL: 5,
            "link_users": False,
            "enable_webhook": False,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert CONF_USER_MEMBERS not in entry.options
