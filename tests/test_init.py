"""Setup, entities, actions and webhook tests."""

from __future__ import annotations

import hashlib
import hmac
import json
import time

from homeassistant.components.todo import DOMAIN as TODO_DOMAIN
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import async_capture_events

from custom_components.yakka.const import (
    CONF_WEBHOOK_ID,
    CONF_WEBHOOK_SECRET,
    DOMAIN,
    EVENT_YAKKA,
)

from .fixtures import chore, completion
from .helpers import API, make_entry, mock_api


def _entity_id(hass: HomeAssistant, platform: str, suffix: str) -> str:
    registry = er.async_get(hass)
    for ent in registry.entities.values():
        if ent.platform == DOMAIN and ent.domain == platform and ent.unique_id.endswith(suffix):
            return ent.entity_id
    raise AssertionError(f"no {platform} entity ending {suffix}")


async def _setup(hass, aioclient_mock, **options):
    mock_api(aioclient_mock)
    entry = make_entry(**options)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_entities(hass: HomeAssistant, aioclient_mock) -> None:
    entry = await _setup(hass, aioclient_mock)
    assert entry.state is ConfigEntryState.LOADED

    status = hass.states.get(_entity_id(hass, "sensor", "_ch1_status"))
    assert status.state == "overdue"
    assert status.attributes["assignee"] == "Sam"
    assert hass.states.get(_entity_id(hass, "sensor", "_ch1_assignee")).state == "Sam"
    assert hass.states.get(_entity_id(hass, "sensor", "_due_chores")).state == "1"
    assert hass.states.get(_entity_id(hass, "sensor", "_overdue_chores")).state == "1"
    # The to-do list counts open items: only the overdue chore.
    assert hass.states.get(_entity_id(hass, "todo", "_chores")).state == "1"

    # The group id (the group's access secret) isn't in any unique id.
    for ent in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id):
        assert "grp_secret" not in ent.unique_id

    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_auth_failure_starts_reauth(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.get(
        f"{API}/chores", status=401, json={"error": {"code": "TOKEN_INVALID", "message": "x"}}
    )
    aioclient_mock.get(f"{API}/members", status=401, json={"error": {"code": "TOKEN_INVALID"}})
    entry = make_entry()
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert any(f["context"]["source"] == "reauth" for f in hass.config_entries.flow.async_progress())


async def test_button_and_todo_complete(hass: HomeAssistant, aioclient_mock) -> None:
    await _setup(hass, aioclient_mock, default_member="m1")
    aioclient_mock.post(
        f"{API}/chores/ch1/complete",
        json={"completion": completion(), "deduplicated": False, "nextDueAt": None,
              "chore": chore(status="upcoming", last=completion())},
        status=201,
    )
    await hass.services.async_call(
        "button", "press", {"entity_id": _entity_id(hass, "button", "_ch1_complete")}, blocking=True
    )
    call = aioclient_mock.mock_calls[-1]
    assert str(call[1]).endswith("/chores/ch1/complete")
    assert call[2] == {"member": "m1"}
    # Patched in from the response without waiting for a poll.
    assert hass.states.get(_entity_id(hass, "sensor", "_ch1_status")).state == "upcoming"
    assert hass.states.get(_entity_id(hass, "todo", "_chores")).state == "0"

    # Unticking undoes the last completion.
    aioclient_mock.post(
        f"{API}/completions/c1/undo",
        json={"completion": completion(undone="2026-11-14T00:00:00Z"), "alreadyUndone": False,
              "nextDueAt": None, "chore": chore(status="overdue")},
    )
    await hass.services.async_call(
        TODO_DOMAIN,
        "update_item",
        {"entity_id": _entity_id(hass, "todo", "_chores"), "item": "ch1", "status": "needs_action"},
        blocking=True,
    )
    assert str(aioclient_mock.mock_calls[-1][1]).endswith("/completions/c1/undo")
    assert hass.states.get(_entity_id(hass, "todo", "_chores")).state == "1"


async def test_complete_chore_action(hass: HomeAssistant, aioclient_mock) -> None:
    await _setup(hass, aioclient_mock)
    aioclient_mock.post(
        f"{API}/chores/ch2/complete",
        json={"completion": completion("c9", "ch2", ("m2", "Sam")), "deduplicated": True,
              "nextDueAt": "2026-11-20T09:00:00.000Z", "chore": chore("ch2", "Dishes", status="upcoming")},
    )
    response = await hass.services.async_call(
        DOMAIN,
        "complete_chore",
        {"chore": "dishes", "member": "Sam", "note": "done"},
        blocking=True,
        return_response=True,
    )
    assert response["completion_id"] == "c9"
    assert response["deduplicated"] is True
    assert aioclient_mock.mock_calls[-1][2] == {"member": "Sam", "note": "done"}


async def test_webhook(hass: HomeAssistant, aioclient_mock, hass_client_no_auth) -> None:
    await _setup(hass, aioclient_mock, **{CONF_WEBHOOK_ID: "hook123", CONF_WEBHOOK_SECRET: "whsec_s"})
    events = async_capture_events(hass, EVENT_YAKKA)
    client = await hass_client_no_auth()
    body = json.dumps({"id": "evt_1", "type": "chore.overdue", "createdAt": "x",
                       "group": {"name": "Home"}, "data": {"chore": {"id": "ch1"}}}).encode()
    ts = str(int(time.time()))
    sig = "sha256=" + hmac.new(b"whsec_s", ts.encode() + b"." + body, hashlib.sha256).hexdigest()
    headers = {"X-Yakka-Timestamp": ts, "X-Signature": sig, "Content-Type": "application/json"}

    resp = await client.post("/api/webhook/hook123", data=body, headers={**headers, "X-Signature": "sha256=0"})
    assert resp.status == 401
    resp = await client.post("/api/webhook/hook123", data=body, headers=headers)
    assert resp.status == 204
    resp = await client.post("/api/webhook/hook123", data=body, headers=headers)  # retry, deduplicated
    assert resp.status == 204
    await hass.async_block_till_done()
    assert len(events) == 1
    assert events[0].data["type"] == "chore.overdue"
    assert events[0].data["data"]["chore"]["id"] == "ch1"
