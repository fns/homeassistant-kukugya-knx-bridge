#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Deque

from aiohttp import ClientSession, ClientTimeout, WSMsgType, web

LOG = logging.getLogger("kukugya.knx_bridge")
OPTIONS_PATH = Path("/data/options.json")
DEFAULT_OPTIONS = {
    "homeassistant_url": "ws://supervisor/core/websocket",
    "bind_host": "0.0.0.0",
    "bind_port": 8099,
    "event_buffer_size": 1000,
}


@dataclass(slots=True)
class BridgeEvent:
    time_fired: str
    event_type: str
    data: dict[str, Any]


@dataclass(slots=True)
class EntitySnapshot:
    entity_id: str
    domain: str
    state: Any
    attributes: dict[str, Any]
    last_changed: str | None
    last_updated: str | None
    context: dict[str, Any] | None


class KukugyaKnxBridge:
    def __init__(self) -> None:
        options = self._load_options()
        self.homeassistant_url = str(options.get("homeassistant_url") or DEFAULT_OPTIONS["homeassistant_url"]).strip()
        self.bind_host = str(options.get("bind_host") or DEFAULT_OPTIONS["bind_host"]).strip()
        self.bind_port = int(options.get("bind_port") or DEFAULT_OPTIONS["bind_port"])
        self.event_buffer: Deque[BridgeEvent] = deque(
            maxlen=int(options.get("event_buffer_size") or DEFAULT_OPTIONS["event_buffer_size"])
        )
        self.entities: dict[str, EntitySnapshot] = {}
        self._session: ClientSession | None = None
        self._ha_task: asyncio.Task[None] | None = None
        self._ha_connected = False
        self._last_error: str | None = None
        self._last_seen_at: str | None = None
        self._shutdown = asyncio.Event()
        self._app: web.Application | None = None

    def _load_options(self) -> dict[str, Any]:
        try:
            return json.loads(OPTIONS_PATH.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except Exception as exc:  # pragma: no cover - defensive; add-on must boot even with broken config
            LOG.warning("Could not load options.json: %s", exc)
            return {}

    @property
    def token(self) -> str:
        return os.environ.get("SUPERVISOR_TOKEN", "").strip()

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _record(self, event_type: str, data: dict[str, Any]) -> None:
        now = self._now()
        self.event_buffer.append(BridgeEvent(time_fired=now, event_type=event_type, data=data))
        self._last_seen_at = now

    def _entity_snapshot_from_state(self, state: dict[str, Any]) -> EntitySnapshot:
        entity_id = str(state.get("entity_id") or "")
        domain = entity_id.split(".", 1)[0] if "." in entity_id else ""
        attributes = state.get("attributes") if isinstance(state.get("attributes"), dict) else {}
        context = state.get("context") if isinstance(state.get("context"), dict) else None
        return EntitySnapshot(
            entity_id=entity_id,
            domain=domain,
            state=state.get("state"),
            attributes=attributes,
            last_changed=state.get("last_changed"),
            last_updated=state.get("last_updated"),
            context=context,
        )

    def _apply_state_changed(self, data: dict[str, Any]) -> None:
        entity_id = str(data.get("entity_id") or "")
        new_state = data.get("new_state")
        old_state = data.get("old_state") if isinstance(data.get("old_state"), dict) else None
        normalized: dict[str, Any] = {"entity_id": entity_id}
        if old_state:
            normalized["old_state"] = old_state.get("state")
        if isinstance(new_state, dict):
            normalized["new_state"] = new_state.get("state")
            normalized["attributes"] = new_state.get("attributes") if isinstance(new_state.get("attributes"), dict) else {}
            normalized["last_changed"] = new_state.get("last_changed")
            normalized["last_updated"] = new_state.get("last_updated")
            normalized["context"] = new_state.get("context") if isinstance(new_state.get("context"), dict) else None
            self.entities[entity_id] = self._entity_snapshot_from_state(new_state)
        elif entity_id:
            self.entities.pop(entity_id, None)
        self._record("state_changed", normalized)

    def _apply_knx_event(self, data: dict[str, Any]) -> None:
        normalized = {
            "source": data.get("source"),
            "destination": data.get("destination"),
            "direction": data.get("direction"),
            "telegramtype": data.get("telegramtype"),
            "value": data.get("value"),
            "data": data.get("data"),
        }
        self._record("knx_event", normalized)

    def snapshot_events(
        self,
        *,
        limit: int = 200,
        event_type: str | None = None,
    ) -> list[dict[str, Any]]:
        items = list(self.event_buffer)[-max(1, limit) :]
        if event_type:
            items = [item for item in items if item.event_type == event_type]
        return [asdict(item) for item in items]

    def snapshot_entities(
        self,
        *,
        limit: int = 500,
        domain: str | None = None,
        state: str | None = None,
        query: str | None = None,
    ) -> list[dict[str, Any]]:
        items = list(self.entities.values())
        if domain:
            items = [item for item in items if item.domain == domain]
        if state:
            items = [item for item in items if str(item.state) == state]
        if query:
            query_lc = query.lower()
            items = [
                item
                for item in items
                if query_lc in item.entity_id.lower()
                or query_lc in json.dumps(item.attributes, ensure_ascii=False, default=str).lower()
                or query_lc in str(item.state).lower()
            ]
        items = items[: max(1, limit)]
        return [asdict(item) for item in items]

    def get_entity(self, entity_id: str) -> dict[str, Any] | None:
        entity = self.entities.get(entity_id)
        return asdict(entity) if entity else None

    async def start(self) -> None:
        timeout = ClientTimeout(total=30)
        self._session = ClientSession(timeout=timeout)
        self._ha_task = asyncio.create_task(self._ha_loop(), name="ha-websocket-loop")

    async def stop(self) -> None:
        self._shutdown.set()
        if self._ha_task:
            self._ha_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._ha_task
        if self._session:
            await self._session.close()

    async def _authenticate(self, ws: Any) -> None:
        if not self.token:
            raise RuntimeError("SUPERVISOR_TOKEN is missing")
        auth_msg = await ws.receive()
        if auth_msg.type != WSMsgType.TEXT:
            raise RuntimeError("Home Assistant websocket did not request auth")
        auth_payload = json.loads(auth_msg.data)
        if auth_payload.get("type") != "auth_required":
            raise RuntimeError(f"Unexpected websocket auth prelude: {auth_payload}")
        await ws.send_json({"type": "auth", "access_token": self.token})
        auth_result = await ws.receive_json()
        if auth_result.get("type") != "auth_ok":
            raise RuntimeError(f"Home Assistant auth failed: {auth_result}")

    async def _subscribe(self, ws: Any, message_id: int, event_type: str) -> None:
        await ws.send_json({"id": message_id, "type": "subscribe_events", "event_type": event_type})
        response = await ws.receive_json()
        if not response.get("success", False):
            raise RuntimeError(f"Could not subscribe to {event_type}: {response}")

    async def _ha_call_service(
        self,
        *,
        domain: str,
        service: str,
        target: dict[str, Any] | None = None,
        service_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not self._session:
            raise RuntimeError("Bridge session is not ready")
        async with self._session.ws_connect(self.homeassistant_url, heartbeat=30) as ws:
            await self._authenticate(ws)
            payload: dict[str, Any] = {"id": 1, "type": "call_service", "domain": domain, "service": service}
            if target:
                payload["target"] = target
            if service_data:
                payload["service_data"] = service_data
            await ws.send_json(payload)
            response = await ws.receive_json()
            if response.get("type") != "result" or not response.get("success", False):
                raise RuntimeError(f"Home Assistant service call failed: {response}")
            return response

    async def _ha_loop(self) -> None:
        backoff = 1
        while not self._shutdown.is_set():
            try:
                if not self._session:
                    await asyncio.sleep(1)
                    continue
                async with self._session.ws_connect(self.homeassistant_url, heartbeat=30) as ws:
                    await self._authenticate(ws)
                    self._ha_connected = True
                    self._last_error = None
                    backoff = 1
                    await self._subscribe(ws, 1, "state_changed")
                    await self._subscribe(ws, 2, "knx_event")
                    self._record("bridge_connected", {"homeassistant_url": self.homeassistant_url})
                    async for message in ws:
                        if message.type != WSMsgType.TEXT:
                            continue
                        payload = json.loads(message.data)
                        if payload.get("type") != "event":
                            continue
                        event = payload.get("event") or {}
                        event_type = str(event.get("event_type") or "unknown")
                        data = event.get("data") if isinstance(event.get("data"), dict) else {}
                        if event_type == "state_changed":
                            self._apply_state_changed(data)
                        elif event_type == "knx_event":
                            self._apply_knx_event(data)
                        else:
                            self._record(event_type, data)
            except asyncio.CancelledError:
                break
            except Exception as exc:  # pragma: no cover - runtime bridge resilience
                self._ha_connected = False
                self._last_error = str(exc)
                LOG.exception("Home Assistant websocket loop failed")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)
        self._ha_connected = False

    def build_app(self) -> web.Application:
        app = web.Application()
        app["bridge"] = self

        async def health(_: web.Request) -> web.Response:
            return web.json_response(
                {
                    "ok": True,
                    "connected": self._ha_connected,
                    "last_seen_at": self._last_seen_at,
                    "last_error": self._last_error,
                    "buffered_events": len(self.event_buffer),
                    "entity_count": len(self.entities),
                    "homeassistant_url": self.homeassistant_url,
                }
            )

        async def root(_: web.Request) -> web.Response:
            return web.json_response(
                {
                    "name": "Kukugya KNX Bridge",
                    "status": "running",
                    "health": "/health",
                    "events": "/events",
                    "entities": "/entities",
                    "entity": "/entities/{entity_id}",
                    "telegrams": "/telegrams",
                    "command": "/command",
                }
            )

        async def events(request: web.Request) -> web.Response:
            limit = int(request.query.get("limit", "200") or 200)
            event_type = request.query.get("type", "").strip() or None
            items = self.snapshot_events(limit=limit, event_type=event_type)
            return web.json_response({"items": items, "count": len(items)})

        async def entities(request: web.Request) -> web.Response:
            limit = int(request.query.get("limit", "500") or 500)
            domain = request.query.get("domain", "").strip() or None
            state = request.query.get("state", "").strip() or None
            query = request.query.get("q", "").strip() or None
            items = self.snapshot_entities(limit=limit, domain=domain, state=state, query=query)
            return web.json_response({"items": items, "count": len(items)})

        async def entity_detail(request: web.Request) -> web.Response:
            entity_id = request.match_info["entity_id"]
            entity = self.get_entity(entity_id)
            if not entity:
                raise web.HTTPNotFound(text=f"Unknown entity: {entity_id}")
            return web.json_response(entity)

        async def telegrams(request: web.Request) -> web.Response:
            limit = int(request.query.get("limit", "200") or 200)
            destination = request.query.get("destination", "").strip()
            source = request.query.get("source", "").strip()
            direction = request.query.get("direction", "").strip()
            items = self.snapshot_events(limit=limit, event_type="knx_event")
            if destination:
                items = [item for item in items if str(item["data"].get("destination") or "") == destination]
            if source:
                items = [item for item in items if str(item["data"].get("source") or "") == source]
            if direction:
                items = [item for item in items if str(item["data"].get("direction") or "") == direction]
            return web.json_response({"items": items, "count": len(items)})

        async def command(request: web.Request) -> web.Response:
            try:
                payload = await request.json()
            except Exception as exc:
                raise web.HTTPBadRequest(text=f"Invalid JSON body: {exc}") from exc
            kind = str(payload.get("kind") or "").strip()
            if not kind:
                raise web.HTTPBadRequest(text="Missing command kind")
            if kind == "knx.send":
                data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
                response = await self._ha_call_service(domain="knx", service="send", service_data=data)
            elif kind == "service":
                service = payload.get("service")
                domain = payload.get("domain")
                if not isinstance(service, str) or not isinstance(domain, str):
                    raise web.HTTPBadRequest(text="Missing domain/service for service command")
                target = payload.get("target") if isinstance(payload.get("target"), dict) else None
                service_data = payload.get("service_data") if isinstance(payload.get("service_data"), dict) else None
                response = await self._ha_call_service(
                    domain=domain,
                    service=service,
                    target=target,
                    service_data=service_data,
                )
            else:
                raise web.HTTPBadRequest(text=f"Unsupported command kind: {kind}")
            self._record("bridge_command", {"kind": kind, "payload": payload})
            return web.json_response({"ok": True, "response": response})

        async def snapshot(_: web.Request) -> web.Response:
            return web.json_response(
                {
                    "health": {
                        "connected": self._ha_connected,
                        "last_seen_at": self._last_seen_at,
                        "last_error": self._last_error,
                    },
                    "counts": {
                        "events": len(self.event_buffer),
                        "entities": len(self.entities),
                    },
                    "recent_events": self.snapshot_events(limit=20),
                    "recent_entities": self.snapshot_entities(limit=20),
                }
            )

        async def cors_options(_: web.Request) -> web.Response:
            return web.Response(status=204)

        app.add_routes(
            [
                web.get("/", root),
                web.get("/health", health),
                web.get("/events", events),
                web.get("/entities", entities),
                web.get("/entities/{entity_id}", entity_detail),
                web.get("/telegrams", telegrams),
                web.get("/snapshot", snapshot),
                web.post("/command", command),
                web.options("/health", cors_options),
                web.options("/events", cors_options),
                web.options("/entities", cors_options),
                web.options("/entities/{entity_id}", cors_options),
                web.options("/telegrams", cors_options),
                web.options("/snapshot", cors_options),
                web.options("/command", cors_options),
            ]
        )

        @web.middleware
        async def cors_middleware(request: web.Request, handler: Any) -> web.StreamResponse:
            if request.method == "OPTIONS":
                response = await cors_options(request)
            else:
                response = await handler(request)
            response.headers["Access-Control-Allow-Origin"] = "*"
            response.headers["Access-Control-Allow-Headers"] = "content-type, authorization"
            response.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
            return response

        app.middlewares.append(cors_middleware)
        self._app = app
        return app


def load_bridge() -> KukugyaKnxBridge:
    return KukugyaKnxBridge()


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    bridge = load_bridge()
    await bridge.start()
    app = bridge.build_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host=bridge.bind_host, port=bridge.bind_port)
    await site.start()
    LOG.info("Kukugya KNX Bridge listening on http://%s:%s", bridge.bind_host, bridge.bind_port)
    try:
        await bridge._shutdown.wait()
    finally:
        await bridge.stop()
        await runner.cleanup()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
