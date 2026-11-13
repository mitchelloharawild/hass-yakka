"""Sample API responses, in the shapes documented in Yakka's docs/API.md."""

GROUP_ID = "grp_secret_123"
TOKEN = "yk_testtoken"

MEMBERS = {
    "members": [
        {"id": "m1", "name": "Alex", "colour": "#f00", "archived": False},
        {"id": "m2", "name": "Sam", "colour": None, "archived": False},
    ]
}


def completion(cid="c1", chore="ch1", member=("m1", "Alex"), undone=None):
    return {
        "id": cid,
        "choreId": chore,
        "source": "API",
        "completedAt": "2026-11-13T09:30:00.000Z",
        "createdAt": "2026-11-13T09:30:00.000Z",
        "undoneAt": undone,
        "note": None,
        "member": {"id": member[0], "name": member[1]} if member else None,
    }


def chore(cid="ch1", title="Bins", status="overdue", icon="🗑️", last=None, assignee="m2"):
    return {
        "id": cid,
        "title": title,
        "description": None,
        "icon": icon,
        "checklist": [],
        "rrule": "FREQ=WEEKLY",
        "startsAt": "2026-01-01T00:00:00.000Z",
        "anchor": "DUE_DATE",
        "graceMinutes": 90,
        "assigneeMode": "ROUND_ROBIN",
        "currentAssigneeId": assignee,
        "archived": False,
        "status": status,
        "nextDueAt": "2026-11-14T09:00:00.000Z",
        "overdueAt": "2026-11-14T10:30:00.000Z",
        "dueToday": True,
        "missedCount": 0,
        "adaptive": None,
        "lastCompletion": last,
    }


CHORES = {
    "chores": [
        chore(),
        chore(
            "ch2",
            "Dishes",
            status="upcoming",
            icon=None,
            last=completion("c2", "ch2"),
            assignee=None,
        ),
    ]
}

EXPORT = {"format": "yakka.group", "version": 1, "group": {"name": "Home", "timezone": "UTC"}}
