"""Shared actions: complete and undo, with error handling."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import Any

from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from .api import Chore, YakkaApiError, YakkaAuthError, YakkaError
from .const import DOMAIN
from .coordinator import YakkaCoordinator

# API error codes caused by what the caller asked for, not by Yakka.
_VALIDATION_CODES = {
    "CHORE_NOT_FOUND",
    "CHORE_ARCHIVED",
    "MEMBER_NOT_FOUND",
    "MEMBER_AMBIGUOUS",
    "MEMBER_ARCHIVED",
    "COMPLETION_NOT_FOUND",
    "COMPLETED_AT_OUT_OF_RANGE",
    "VALIDATION_FAILED",
}


def _raise(err: YakkaError) -> None:
    if isinstance(err, YakkaApiError) and err.code in _VALIDATION_CODES:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="api_rejected",
            translation_placeholders={"code": err.code, "message": str(err)},
        ) from err
    if isinstance(err, YakkaAuthError):
        raise HomeAssistantError(
            translation_domain=DOMAIN, translation_key="auth_failed"
        ) from err
    raise HomeAssistantError(
        translation_domain=DOMAIN,
        translation_key="request_failed",
        translation_placeholders={"error": str(err)},
    ) from err


def _apply(coordinator: YakkaCoordinator, response: dict[str, Any]) -> None:
    """Patch the returned chore into the coordinator so entities update now."""
    raw = response.get("chore")
    if not isinstance(raw, dict) or coordinator.data is None:
        return
    chore = Chore.from_json(raw)
    chores = dict(coordinator.data.chores)
    if chore.archived:
        chores.pop(chore.id, None)
    else:
        chores[chore.id] = chore
    coordinator.async_set_updated_data(replace(coordinator.data, chores=chores))


async def async_complete(
    coordinator: YakkaCoordinator,
    chore_id: str,
    member: str | None = None,
    note: str | None = None,
    completed_at: datetime | None = None,
) -> dict[str, Any]:
    """Complete a chore and update entities from the response."""
    try:
        response = await coordinator.client.complete_chore(
            chore_id, member=member, note=note, completed_at=completed_at
        )
    except YakkaError as err:
        _raise(err)
        raise  # unreachable; keeps type checkers happy
    _apply(coordinator, response)
    return response


async def async_undo(coordinator: YakkaCoordinator, completion_id: str) -> dict[str, Any]:
    """Undo a completion and update entities from the response."""
    try:
        response = await coordinator.client.undo_completion(completion_id)
    except YakkaError as err:
        _raise(err)
        raise
    _apply(coordinator, response)
    return response
