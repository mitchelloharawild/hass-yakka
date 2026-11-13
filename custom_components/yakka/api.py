"""A small async client for the Yakka REST API.

See https://github.com/mitchelloharawild/yakka/blob/main/docs/API.md
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit

import aiohttp

REQUEST_TIMEOUT = 15


class YakkaError(Exception):
    """Base error for the Yakka client."""


class YakkaConnectionError(YakkaError):
    """Yakka could not be reached."""


class YakkaApiError(YakkaError):
    """Yakka answered with an error response."""

    def __init__(self, status: int, code: str, message: str | None = None) -> None:
        super().__init__(message or code)
        self.status = status
        self.code = code


class YakkaAuthError(YakkaApiError):
    """The API token is missing, invalid, revoked or for another group."""


def parse_group_link(text: str) -> tuple[str, str]:
    """Split a Yakka group link into (base_url, group_id).

    Accepts links such as ``https://yakka.example/groups/abc123``, with or
    without a trailing page (``/integrations``), query or fragment, and with
    or without a scheme (``https://`` is assumed). The base URL keeps any
    path prefix in front of ``/groups/`` so instances served from a subpath
    work too.
    """
    text = text.strip()
    if not text:
        raise ValueError("empty")
    if "://" not in text:
        text = f"https://{text}"
    parts = urlsplit(text)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError("not an http(s) URL")
    segments = parts.path.split("/")
    try:
        idx = segments.index("groups")
    except ValueError as err:
        raise ValueError("no /groups/ segment") from err
    if idx + 1 >= len(segments) or not segments[idx + 1]:
        raise ValueError("no group id")
    group_id = segments[idx + 1]
    prefix = "/".join(segments[:idx]).rstrip("/")
    return f"{parts.scheme}://{parts.netloc}{prefix}", group_id


def _dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


@dataclass(slots=True, frozen=True)
class Member:
    """A group member."""

    id: str
    name: str
    colour: str | None
    archived: bool

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Member:
        """Build from API JSON."""
        return cls(
            id=data["id"],
            name=data["name"],
            colour=data.get("colour"),
            archived=bool(data.get("archived", False)),
        )


@dataclass(slots=True, frozen=True)
class Completion:
    """A recorded completion of a chore."""

    id: str
    chore_id: str
    source: str
    completed_at: datetime | None
    undone_at: datetime | None
    note: str | None
    member_id: str | None
    member_name: str | None

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Completion:
        """Build from API JSON."""
        member = data.get("member") or {}
        return cls(
            id=data["id"],
            chore_id=data.get("choreId", ""),
            source=data.get("source", ""),
            completed_at=_dt(data.get("completedAt")),
            undone_at=_dt(data.get("undoneAt")),
            note=data.get("note"),
            member_id=member.get("id"),
            member_name=member.get("name"),
        )


@dataclass(slots=True, frozen=True)
class Chore:
    """A chore with its schedule worked out by Yakka."""

    id: str
    title: str
    description: str | None
    icon: str | None
    checklist: list[str]
    rrule: str | None
    anchor: str | None
    grace_minutes: int | None
    assignee_mode: str | None
    current_assignee_id: str | None
    archived: bool
    status: str
    next_due_at: datetime | None
    overdue_at: datetime | None
    due_today: bool
    missed_count: int
    adaptive: dict[str, Any] | None
    last_completion: Completion | None

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Chore:
        """Build from API JSON."""
        last = data.get("lastCompletion")
        return cls(
            id=data["id"],
            title=data["title"],
            description=data.get("description"),
            icon=data.get("icon"),
            checklist=list(data.get("checklist") or []),
            rrule=data.get("rrule"),
            anchor=data.get("anchor"),
            grace_minutes=data.get("graceMinutes"),
            assignee_mode=data.get("assigneeMode"),
            current_assignee_id=data.get("currentAssigneeId"),
            archived=bool(data.get("archived", False)),
            status=data.get("status", "unscheduled"),
            next_due_at=_dt(data.get("nextDueAt")),
            overdue_at=_dt(data.get("overdueAt")),
            due_today=bool(data.get("dueToday", False)),
            missed_count=int(data.get("missedCount") or 0),
            adaptive=data.get("adaptive"),
            last_completion=Completion.from_json(last) if last else None,
        )

    @property
    def display_name(self) -> str:
        """Title with the chore's emoji in front, if it has one."""
        return f"{self.icon} {self.title}" if self.icon else self.title


class YakkaClient:
    """Talks to one group on one Yakka instance."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        base_url: str,
        group_id: str,
        token: str,
    ) -> None:
        """Initialise the client."""
        self._session = session
        self.base_url = base_url.rstrip("/")
        self.group_id = group_id
        self._token = token

    @property
    def group_url(self) -> str:
        """The group's page in the Yakka web app."""
        return f"{self.base_url}/groups/{self.group_id}"

    async def _request(
        self, method: str, path: str, json: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        url = f"{self.base_url}/api/v1/groups/{self.group_id}{path}"
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/json",
        }
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT):
                resp = await self._session.request(
                    method, url, headers=headers, json=json
                )
                try:
                    body: Any = await resp.json(content_type=None)
                except (aiohttp.ContentTypeError, ValueError):
                    body = None
        except (TimeoutError, aiohttp.ClientError) as err:
            raise YakkaConnectionError(str(err) or type(err).__name__) from err

        if resp.status >= 400:
            error = body.get("error", {}) if isinstance(body, dict) else {}
            code = error.get("code") or f"HTTP_{resp.status}"
            message = error.get("message")
            if resp.status in (401, 403):
                raise YakkaAuthError(resp.status, code, message)
            raise YakkaApiError(resp.status, code, message)
        if not isinstance(body, dict):
            raise YakkaApiError(resp.status, "INVALID_RESPONSE", "Expected a JSON object")
        return body

    async def get_chores(self) -> list[Chore]:
        """List the group's active chores, most urgent first."""
        data = await self._request("GET", "/chores")
        return [Chore.from_json(c) for c in data.get("chores", [])]

    async def get_members(self, include_archived: bool = False) -> list[Member]:
        """List the group's members, oldest first."""
        path = "/members?archived=true" if include_archived else "/members"
        data = await self._request("GET", path)
        return [Member.from_json(m) for m in data.get("members", [])]

    async def get_group_name(self) -> str | None:
        """Read the group's name from the export, or None if that fails.

        The API has no group endpoint, so this uses the export. It's only
        called once, when the integration is set up.
        """
        try:
            data = await self._request("GET", "/export")
        except YakkaError:
            return None
        group = data.get("group")
        name = group.get("name") if isinstance(group, dict) else None
        return name if isinstance(name, str) and name.strip() else None

    async def complete_chore(
        self,
        chore_id: str,
        member: str | None = None,
        note: str | None = None,
        completed_at: datetime | None = None,
    ) -> dict[str, Any]:
        """Mark a chore as done. Returns the API response."""
        payload: dict[str, Any] = {}
        if member:
            payload["member"] = member
        if note:
            payload["note"] = note
        if completed_at:
            payload["completedAt"] = completed_at.isoformat()
        return await self._request(
            "POST", f"/chores/{chore_id}/complete", json=payload
        )

    async def undo_completion(self, completion_id: str) -> dict[str, Any]:
        """Undo a completion. Undoing twice is harmless."""
        return await self._request("POST", f"/completions/{completion_id}/undo")
