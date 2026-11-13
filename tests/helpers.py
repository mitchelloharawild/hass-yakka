"""Shared setup for Home Assistant tests."""

from __future__ import annotations

from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.yakka.config_flow import group_unique_id
from custom_components.yakka.const import CONF_BASE_URL, CONF_GROUP_ID, CONF_TOKEN, DOMAIN

from .fixtures import CHORES, EXPORT, GROUP_ID, MEMBERS, TOKEN

BASE = "https://yakka.example"
API = f"{BASE}/api/v1/groups/{GROUP_ID}"


def mock_api(aioclient_mock: AiohttpClientMocker, chores=CHORES) -> None:
    aioclient_mock.get(f"{API}/chores", json=chores)
    aioclient_mock.get(f"{API}/members", json=MEMBERS)
    aioclient_mock.get(f"{API}/export", json=EXPORT)


def make_entry(**options) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="Home",
        unique_id=group_unique_id(BASE, GROUP_ID),
        data={CONF_BASE_URL: BASE, CONF_GROUP_ID: GROUP_ID, CONF_TOKEN: TOKEN},
        options=options,
    )
