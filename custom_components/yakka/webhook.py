"""Receives Yakka's signed outbound webhooks.

Each verified event is fired on the bus as ``yakka_event`` and triggers a
refresh, so entities update straight away instead of on the next poll.
"""

from __future__ import annotations

from collections import deque
from http import HTTPStatus
import json
import logging

from aiohttp import web

from homeassistant.components import webhook
from homeassistant.core import HomeAssistant, callback

from .const import CONF_WEBHOOK_ID, CONF_WEBHOOK_SECRET, DOMAIN, EVENT_YAKKA
from .coordinator import YakkaConfigEntry
from .signing import verify_signature

_LOGGER = logging.getLogger(__name__)
MAX_BODY = 256 * 1024


@callback
def async_register_webhook(hass: HomeAssistant, entry: YakkaConfigEntry) -> None:
    """Register the entry's webhook, if it has one configured."""
    webhook_id = entry.options.get(CONF_WEBHOOK_ID)
    secret = entry.options.get(CONF_WEBHOOK_SECRET)
    if not webhook_id or not secret:
        return

    seen: deque[str] = deque(maxlen=200)

    async def _handle(
        hass: HomeAssistant, webhook_id: str, request: web.Request
    ) -> web.Response:
        if request.content_length and request.content_length > MAX_BODY:
            return web.Response(status=HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
        body = await request.read()
        if len(body) > MAX_BODY:
            return web.Response(status=HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
        if not verify_signature(
            secret,
            request.headers.get("X-Yakka-Timestamp"),
            request.headers.get("X-Signature"),
            body,
        ):
            _LOGGER.warning("Rejected a Yakka webhook with a bad or stale signature")
            return web.Response(status=HTTPStatus.UNAUTHORIZED)
        try:
            event = json.loads(body)
        except ValueError:
            return web.Response(status=HTTPStatus.BAD_REQUEST)
        if not isinstance(event, dict):
            return web.Response(status=HTTPStatus.BAD_REQUEST)

        event_id = event.get("id")
        if isinstance(event_id, str):
            if event_id in seen:
                return web.Response(status=HTTPStatus.NO_CONTENT)
            seen.append(event_id)

        hass.bus.async_fire(
            EVENT_YAKKA,
            {
                "config_entry_id": entry.entry_id,
                "id": event_id,
                "type": event.get("type"),
                "created_at": event.get("createdAt"),
                "group": event.get("group"),
                "data": event.get("data"),
            },
        )
        if event.get("type") != "ping":
            await entry.runtime_data.async_request_refresh()
        return web.Response(status=HTTPStatus.NO_CONTENT)

    webhook.async_register(
        hass,
        DOMAIN,
        f"Yakka: {entry.title}",
        webhook_id,
        _handle,
        allowed_methods=[webhook.METH_POST],
    )
    entry.async_on_unload(lambda: webhook.async_unregister(hass, webhook_id))
