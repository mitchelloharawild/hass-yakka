"""The group device, chore events, and device triggers, conditions and actions."""

from __future__ import annotations

from pytest_homeassistant_custom_component.common import (
    async_capture_events,
    async_get_device_automation_capabilities,
    async_get_device_automations,
    async_mock_service,
)

from homeassistant.components import automation
from homeassistant.components.device_automation import DeviceAutomationType
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.setup import async_setup_component

from .fixtures import CHORES, chore, completion
from .helpers import API, make_entry, mock_api
from custom_components.yakka import device_action, device_condition
from custom_components.yakka.const import DOMAIN, EVENT_YAKKA_CHORE
from custom_components.yakka.coordinator import group_device_identifier


async def _setup(hass: HomeAssistant, aioclient_mock):
    mock_api(aioclient_mock)
    entry = make_entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    device = dr.async_get(hass).async_get_device(identifiers={group_device_identifier(entry)})
    return entry, device


def _later(c: dict, when: str) -> dict:
    return {**c, "completedAt": when, "createdAt": when}


# After: Bins completed by Sam; the Dishes completion undone, so Dishes is overdue.
CHANGED = {
    "chores": [
        chore(
            status="upcoming",
            last=_later(completion("c5", "ch1", ("m2", "Sam")), "2026-11-14T08:00:00.000Z"),
        ),
        chore("ch2", "Dishes", status="overdue", icon=None, last=None, assignee=None),
    ]
}


async def _poll(hass: HomeAssistant, aioclient_mock, entry, chores) -> None:
    aioclient_mock.clear_requests()
    mock_api(aioclient_mock, chores=chores)
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()


async def test_group_is_the_only_device(hass: HomeAssistant, aioclient_mock) -> None:
    entry, device = await _setup(hass, aioclient_mock)
    devices = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
    assert [d.id for d in devices] == [device.id]
    assert device.name == "Home"

    entities = er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    assert {e.device_id for e in entities} == {device.id}
    status = next(e for e in entities if e.unique_id.endswith("_ch1_status"))
    assert hass.states.get(status.entity_id).name == "Home Bins status"
    button = next(e for e in entities if e.unique_id.endswith("_ch1_complete"))
    assert hass.states.get(button.entity_id).name == "Home Complete Bins"


async def test_archived_chore_entities_removed(hass: HomeAssistant, aioclient_mock) -> None:
    entry, _ = await _setup(hass, aioclient_mock)
    registry = er.async_get(hass)
    await _poll(hass, aioclient_mock, entry, {"chores": [CHORES["chores"][0]]})
    left = {e.unique_id for e in er.async_entries_for_config_entry(registry, entry.entry_id)}
    assert not any("_ch2_" in uid for uid in left)
    assert any("_ch1_" in uid for uid in left)

    # Restored: its entities come back.
    await _poll(hass, aioclient_mock, entry, CHORES)
    left = {e.unique_id for e in er.async_entries_for_config_entry(registry, entry.entry_id)}
    assert any("_ch2_status" in uid for uid in left)


async def test_chore_events(hass: HomeAssistant, aioclient_mock) -> None:
    entry, device = await _setup(hass, aioclient_mock)
    events = async_capture_events(hass, EVENT_YAKKA_CHORE)
    await _poll(hass, aioclient_mock, entry, CHANGED)

    seen = {(e.data["chore_id"], e.data["type"]): e.data for e in events}
    assert set(seen) == {
        ("ch1", "completed"),
        ("ch2", "undone"),
        ("ch2", "due"),
        ("ch2", "overdue"),
    }
    done = seen[("ch1", "completed")]
    assert done["device_id"] == device.id
    assert (done["member"], done["member_id"], done["completion_id"]) == ("Sam", "m2", "c5")
    undone = seen[("ch2", "undone")]
    assert (undone["completion_id"], undone["member"]) == ("c2", "Alex")
    assert seen[("ch2", "due")]["member"] is None

    # Nothing changed, nothing fired.
    events.clear()
    await _poll(hass, aioclient_mock, entry, CHANGED)
    assert events == []


async def test_device_automations_listed(hass: HomeAssistant, aioclient_mock) -> None:
    _, device = await _setup(hass, aioclient_mock)

    async def ours(kind: DeviceAutomationType) -> list[dict]:
        found = await async_get_device_automations(hass, kind, device.id)
        # The device's entities add Home Assistant's generic ones too.
        return [a for a in found if a["domain"] == DOMAIN]

    triggers = await ours(DeviceAutomationType.TRIGGER)
    assert {t["type"] for t in triggers} == {"completed", "undone", "due", "overdue"}
    conditions = await ours(DeviceAutomationType.CONDITION)
    assert {c["type"] for c in conditions} == {"is_due", "is_overdue", "is_not_due"}
    actions = await ours(DeviceAutomationType.ACTION)
    assert {a["type"] for a in actions} == {"complete", "undo_last_completion"}

    # The chore field lists the group's chores.
    completed = next(t for t in triggers if t["type"] == "completed")
    caps = await async_get_device_automation_capabilities(
        hass, DeviceAutomationType.TRIGGER, completed
    )
    fields = {f["name"]: f for f in caps["extra_fields"]}
    assert dict(fields["chore_id"]["options"]) == {"ch1": "🗑️ Bins", "ch2": "Dishes"}
    assert dict(fields["member_id"]["options"]) == {"m1": "Alex", "m2": "Sam"}


async def test_device_trigger_fires(hass: HomeAssistant, aioclient_mock) -> None:
    entry, device = await _setup(hass, aioclient_mock)
    calls = async_mock_service(hass, "test", "automation")
    base = {"platform": "device", "domain": DOMAIN, "device_id": device.id}
    assert await async_setup_component(
        hass,
        automation.DOMAIN,
        {
            automation.DOMAIN: [
                {
                    "triggers": [{**base, "type": "completed", "chore_id": "ch1"}],
                    "actions": {
                        "action": "test.automation",
                        "data": {"who": "{{ trigger.event.data.member }}"},
                    },
                },
                {
                    "triggers": [{**base, "type": "completed", "member_id": "m1"}],
                    "actions": {"action": "test.automation", "data": {"who": "never"}},
                },
                {
                    "triggers": [{**base, "type": "overdue", "chore_id": "ch2"}],
                    "actions": {"action": "test.automation", "data": {"who": "overdue"}},
                },
            ]
        },
    )
    await _poll(hass, aioclient_mock, entry, CHANGED)
    assert sorted(c.data["who"] for c in calls) == ["Sam", "overdue"]


async def test_device_condition_and_action(hass: HomeAssistant, aioclient_mock) -> None:
    _, device = await _setup(hass, aioclient_mock)

    def check(kind: str, chore_id: str) -> bool:
        config = device_condition.CONDITION_SCHEMA(
            {
                "condition": "device",
                "domain": DOMAIN,
                "device_id": device.id,
                "type": kind,
                "chore_id": chore_id,
            }
        )
        return device_condition.async_condition_from_config(hass, config)(hass, {})

    assert check("is_due", "ch1") and check("is_overdue", "ch1")
    assert check("is_not_due", "ch2") and not check("is_due", "ch2")
    assert not check("is_due", "nope")

    aioclient_mock.post(
        f"{API}/chores/ch1/complete",
        json={
            "completion": completion("c7", "ch1", ("m2", "Sam")),
            "deduplicated": False,
            "nextDueAt": None,
            "chore": chore(status="upcoming", last=completion("c7")),
        },
    )
    base = {"domain": DOMAIN, "device_id": device.id, "chore_id": "ch1"}
    await device_action.async_call_action_from_config(
        hass,
        device_action.ACTION_SCHEMA({**base, "type": "complete", "member_id": "m2", "note": "hi"}),
        {},
        None,
    )
    assert aioclient_mock.mock_calls[-1][2] == {"member": "m2", "note": "hi"}
    assert check("is_not_due", "ch1")

    aioclient_mock.post(
        f"{API}/completions/c7/undo",
        json={
            "completion": completion("c7", undone="2026-11-14T00:00:00Z"),
            "alreadyUndone": False,
            "nextDueAt": None,
            "chore": chore(status="overdue"),
        },
    )
    await device_action.async_call_action_from_config(
        hass, device_action.ACTION_SCHEMA({**base, "type": "undo_last_completion"}), {}, None
    )
    assert str(aioclient_mock.mock_calls[-1][1]).endswith("/completions/c7/undo")
    assert check("is_overdue", "ch1")


async def test_undo_action_by_chore(hass: HomeAssistant, aioclient_mock) -> None:
    await _setup(hass, aioclient_mock)
    aioclient_mock.post(
        f"{API}/completions/c2/undo",
        json={
            "completion": completion("c2", "ch2", undone="2026-11-14T00:00:00Z"),
            "alreadyUndone": False,
            "nextDueAt": None,
            "chore": chore("ch2", "Dishes", status="due", icon=None),
        },
    )
    response = await hass.services.async_call(
        DOMAIN, "undo_completion", {"chore": "Dishes"}, blocking=True, return_response=True
    )
    assert response["completion_id"] == "c2"
    assert str(aioclient_mock.mock_calls[-1][1]).endswith("/completions/c2/undo")
