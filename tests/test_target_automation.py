"""Triggers, conditions and actions that pick chores by target."""

from __future__ import annotations

import pytest
from pytest_homeassistant_custom_component.common import async_mock_service

from homeassistant.components import automation
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import (
    condition as condition_helper,
    entity_registry as er,
    service as service_helper,
    trigger as trigger_helper,
)
from homeassistant.loader import async_get_integration
from homeassistant.setup import async_setup_component

from .fixtures import chore, completion
from .helpers import API
from .test_automation import CHANGED, _poll, _setup
from custom_components.yakka.const import DOMAIN


def _entity(hass: HomeAssistant, entry, suffix: str) -> str:
    registry = er.async_get(hass)
    return next(
        e.entity_id
        for e in er.async_entries_for_config_entry(registry, entry.entry_id)
        if e.unique_id.endswith(suffix)
    )


async def test_descriptions(hass: HomeAssistant, aioclient_mock) -> None:
    await _setup(hass, aioclient_mock)
    assert await async_setup_component(hass, automation.DOMAIN, {})
    chore_target = {"entity": [{"integration": DOMAIN}], "device": [{"integration": DOMAIN}]}

    triggers = await trigger_helper.async_get_all_descriptions(hass)
    for key in ("chore_completed", "chore_undone", "chore_due", "chore_overdue"):
        assert triggers[f"{DOMAIN}.{key}"]["target"] == chore_target

    conditions = await condition_helper.async_get_all_descriptions(hass)
    for key in ("chore_is_due", "chore_is_overdue", "chore_is_not_due", "chore_completed_by"):
        assert conditions[f"{DOMAIN}.{key}"]["target"] == chore_target
    assert set(conditions[f"{DOMAIN}.chore_completed_by"]["fields"]) == {"member", "behavior"}

    # Only ours: loading every integration's services.yaml needs extra packages.
    integration = await async_get_integration(hass, DOMAIN)
    services = await hass.async_add_executor_job(service_helper._load_services_file, integration)
    for name in ("complete_chore", "undo_completion"):
        assert services[name]["target"] == {"entity": [{"integration": DOMAIN}]}


async def test_triggers_and_completed_by(hass: HomeAssistant, aioclient_mock) -> None:
    entry, device = await _setup(hass, aioclient_mock)
    bins = _entity(hass, entry, "_ch1_status")
    dishes = _entity(hass, entry, "_ch2_status")
    calls = async_mock_service(hass, "test", "automation")

    def rule(name: str, trigger: str, target: dict, conditions: list | None = None) -> dict:
        return {
            "triggers": [{"trigger": f"{DOMAIN}.{trigger}", "target": target}],
            "conditions": conditions or [],
            "actions": {
                "action": "test.automation",
                "data": {"name": name, "who": "{{ trigger.member }}"},
            },
        }

    def completed_by(member: str) -> dict:
        return {
            "condition": f"{DOMAIN}.chore_completed_by",
            "target": {"entity_id": bins},
            "options": {"member": member},
        }

    assert await async_setup_component(
        hass,
        automation.DOMAIN,
        {
            automation.DOMAIN: [
                rule("bins done", "chore_completed", {"entity_id": bins}),
                rule("dishes done", "chore_completed", {"entity_id": dishes}),
                rule("any undone", "chore_undone", {"device_id": device.id}),
                rule("any overdue", "chore_overdue", {"device_id": device.id}),
                rule("by sam", "chore_completed", {"entity_id": bins}, [completed_by("sam")]),
                rule("by alex", "chore_completed", {"entity_id": bins}, [completed_by("m1")]),
            ]
        },
    )
    await _poll(hass, aioclient_mock, entry, CHANGED)
    assert sorted((c.data["name"], c.data["who"]) for c in calls) == [
        ("any overdue", None),
        ("any undone", "Alex"),
        ("bins done", "Sam"),
        ("by sam", "Sam"),
    ]


async def test_status_conditions(hass: HomeAssistant, aioclient_mock) -> None:
    entry, device = await _setup(hass, aioclient_mock)
    bins = _entity(hass, entry, "_ch1_complete")  # any of a chore's entities works
    dishes = _entity(hass, entry, "_ch2_status")

    async def check(kind: str, target: dict, **options) -> bool:
        config = await condition_helper.async_validate_condition_config(
            hass, {"condition": f"{DOMAIN}.{kind}", "target": target, "options": options}
        )
        test = await condition_helper.async_from_config(hass, config)
        return test(hass, {})

    # Bins is overdue; Dishes is upcoming, last done by Alex.
    assert await check("chore_is_due", {"entity_id": bins})
    assert await check("chore_is_overdue", {"entity_id": bins})
    assert await check("chore_is_not_due", {"entity_id": dishes})
    assert not await check("chore_is_due", {"entity_id": dishes})
    assert await check("chore_is_due", {"device_id": device.id})
    assert not await check("chore_is_due", {"device_id": device.id}, behavior="all")
    assert await check("chore_completed_by", {"entity_id": dishes}, member="Alex")
    assert not await check("chore_completed_by", {"entity_id": bins}, member="Alex")
    # A target with no chores in it fails.
    assert not await check("chore_is_not_due", {"entity_id": "sensor.nope"})


async def test_actions_by_target(hass: HomeAssistant, aioclient_mock) -> None:
    entry, device = await _setup(hass, aioclient_mock)
    bins = _entity(hass, entry, "_ch1_status")
    dishes = _entity(hass, entry, "_ch2_status")
    aioclient_mock.post(
        f"{API}/chores/ch1/complete",
        json={
            "completion": completion("c7", "ch1", ("m2", "Sam")),
            "deduplicated": False,
            "nextDueAt": None,
            "chore": chore(status="upcoming", last=completion("c7")),
        },
    )
    response = await hass.services.async_call(
        DOMAIN,
        "complete_chore",
        {"member": "Sam"},
        target={"entity_id": bins},
        blocking=True,
        return_response=True,
    )
    assert response["completion_id"] == "c7"
    assert str(aioclient_mock.mock_calls[-1][1]).endswith("/chores/ch1/complete")

    # A device, or several chores, is refused rather than completing them all.
    for target in ({"device_id": device.id}, {"entity_id": [bins, dishes]}):
        with pytest.raises(ServiceValidationError) as err:
            await hass.services.async_call(
                DOMAIN, "complete_chore", {}, target=target, blocking=True
            )
        assert err.value.translation_key == "target_one_chore"

    aioclient_mock.post(
        f"{API}/completions/c2/undo",
        json={
            "completion": completion("c2", "ch2", undone="2026-11-14T00:00:00Z"),
            "alreadyUndone": False,
            "nextDueAt": None,
            "chore": chore("ch2", "Dishes", status="due", icon=None),
        },
    )
    await hass.services.async_call(
        DOMAIN, "undo_completion", {}, target={"entity_id": dishes}, blocking=True
    )
    assert str(aioclient_mock.mock_calls[-1][1]).endswith("/completions/c2/undo")
