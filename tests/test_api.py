"""Tests for the HA-free API client and signature check."""

from __future__ import annotations

import hashlib
import hmac
import json

from aiohttp import ClientSession, web
import pytest

from .conftest import load_standalone
from .fixtures import CHORES, EXPORT, GROUP_ID, MEMBERS, TOKEN, chore, completion

api = load_standalone("api")
signing = load_standalone("signing")


@pytest.fixture(autouse=True)
def _allow_sockets():
    """These tests talk to a local fake server.

    The Home Assistant test plugin, when installed, blocks sockets.
    """
    try:
        import pytest_socket
    except ImportError:
        yield
        return
    pytest_socket.enable_socket()
    yield
    pytest_socket.disable_socket(allow_unix_socket=True)


@pytest.mark.parametrize(
    ("link", "expected"),
    [
        ("https://yakka.example/groups/abc", ("https://yakka.example", "abc")),
        ("https://yakka.example/groups/abc/", ("https://yakka.example", "abc")),
        ("https://yakka.example/groups/abc/integrations?x=1#y", ("https://yakka.example", "abc")),
        ("yakka.example/groups/abc", ("https://yakka.example", "abc")),
        ("  http://192.168.1.5:3000/groups/abc  ", ("http://192.168.1.5:3000", "abc")),
        ("https://home.example/yakka/groups/abc", ("https://home.example/yakka", "abc")),
    ],
)
def test_parse_group_link(link, expected):
    assert api.parse_group_link(link) == expected


@pytest.mark.parametrize(
    "link",
    [
        "",
        "https://yakka.example/",
        "https://yakka.example/groups/",
        "ftp://x/groups/a",
        "https:///groups/a",
    ],
)
def test_parse_group_link_rejects(link):
    with pytest.raises(ValueError):
        api.parse_group_link(link)


def test_chore_from_json():
    c = api.Chore.from_json(chore(last=completion()))
    assert c.display_name == "🗑️ Bins"
    assert c.status == "overdue"
    assert c.next_due_at.isoformat() == "2026-11-14T09:00:00+00:00"
    assert c.last_completion.member_name == "Alex"
    assert api.Chore.from_json(chore(icon=None)).display_name == "Bins"


def _sign(secret, ts, body):
    return (
        "sha256=" + hmac.new(secret.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    )


def test_verify_signature():
    body = b'{"type":"ping"}'
    sig = _sign("whsec_x", 1000, body)
    assert signing.verify_signature("whsec_x", "1000", sig, body, now=1000)
    assert signing.verify_signature("whsec_x", "1000", sig, body, now=1299)
    assert not signing.verify_signature("whsec_x", "1000", sig, body, now=1301)  # stale
    assert not signing.verify_signature("whsec_y", "1000", sig, body, now=1000)  # wrong secret
    assert not signing.verify_signature("whsec_x", "1000", sig, body + b" ", now=1000)  # tampered
    assert not signing.verify_signature("whsec_x", None, sig, body, now=1000)
    assert not signing.verify_signature("whsec_x", "abc", sig, body, now=1000)


@pytest.fixture
async def server(aiohttp_server):
    """A fake Yakka that records requests."""
    seen: list[tuple[str, str, dict]] = []

    def authed(request):
        if request.headers.get("Authorization") != f"Bearer {TOKEN}":
            raise web.HTTPUnauthorized(
                text=json.dumps({"error": {"code": "TOKEN_INVALID", "message": "bad"}}),
                content_type="application/json",
            )

    async def chores(request):
        authed(request)
        return web.json_response(CHORES)

    async def members(request):
        authed(request)
        return web.json_response(MEMBERS)

    async def export(request):
        authed(request)
        return web.json_response(EXPORT)

    async def complete(request):
        authed(request)
        body = await request.json()
        seen.append(("complete", request.match_info["cid"], body))
        if body.get("member") == "Nobody":
            return web.json_response(
                {"error": {"code": "MEMBER_NOT_FOUND", "message": "No member"}}, status=404
            )
        return web.json_response(
            {
                "completion": completion(),
                "deduplicated": False,
                "nextDueAt": None,
                "chore": chore(status="upcoming"),
            },
            status=201,
        )

    base = f"/api/v1/groups/{GROUP_ID}"
    app = web.Application()
    app.router.add_get(f"{base}/chores", chores)
    app.router.add_get(f"{base}/members", members)
    app.router.add_get(f"{base}/export", export)
    app.router.add_post(f"{base}/chores/{{cid}}/complete", complete)
    srv = await aiohttp_server(app)
    srv.seen = seen
    return srv


async def test_client_round_trip(server):
    async with ClientSession() as session:
        client = api.YakkaClient(session, str(server.make_url("")), GROUP_ID, TOKEN)
        chores = await client.get_chores()
        assert [c.id for c in chores] == ["ch1", "ch2"]
        members = await client.get_members()
        assert [m.name for m in members] == ["Alex", "Sam"]
        assert await client.get_group_name() == "Home"

        res = await client.complete_chore("ch1", member="Alex", note="hi")
        assert res["chore"]["status"] == "upcoming"
        assert server.seen[-1] == ("complete", "ch1", {"member": "Alex", "note": "hi"})

        with pytest.raises(api.YakkaApiError) as err:
            await client.complete_chore("ch1", member="Nobody")
        assert err.value.code == "MEMBER_NOT_FOUND"
        assert err.value.status == 404


async def test_client_auth_error(server):
    async with ClientSession() as session:
        client = api.YakkaClient(session, str(server.make_url("")), GROUP_ID, "yk_wrong")
        with pytest.raises(api.YakkaAuthError) as err:
            await client.get_chores()
        assert err.value.code == "TOKEN_INVALID"
        assert await client.get_group_name() is None


async def test_client_connection_error():
    async with ClientSession() as session:
        client = api.YakkaClient(session, "http://127.0.0.1:1", GROUP_ID, TOKEN)
        with pytest.raises(api.YakkaConnectionError):
            await client.get_chores()
