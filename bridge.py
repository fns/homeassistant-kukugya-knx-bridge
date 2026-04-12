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


class KukugyaKnxBridge:
    def __init__(self) -> None:
        options = self._load_options()
        self.homeassistant_url = str(options.get("homeassistant_url") or DEFAULT_OPTIONS["homeassistant_url"]).strip()
        self.bind_host = str(options.get("bind_host") or DEFAULT_OPTIONS["bind_host"]).strip()
        self.bind_port = int(options.get("bind_port") or DEFAULT_OPTIONS["bind_port"])
        self.event_buffer: Deque[BridgeEvent] = deque(maxlen=int(options.get("event_buffer_size") or DEFAULT_OPTIONS["event_buffer_size"]))
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

    def snapshot(self, limit: int = 200) -> list[dict[str, Any]]:
        items = list(self.event_buffer)[-max(1, limit) :]
        return [asdict(item) for item in items]

    def _record(self, event_type: str, data: dict[str, Any]) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self.event_buffer.append(BridgeEvent(time_fired=now, event_type=event_type, data=data))
        self._last_seen_at = now

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
        if not self.token:
            raise RuntimeError("SUPERVISOR_TOKEN is missing")
        async with self._session.ws_connect(self.homeassistant_url, heartbeat=30) as ws:
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
            message_id = 1
            payload: dict[str, Any] = {"id": message_id, "type": "call_service", "domain": domain, "service": service}
            if target:
                payload["target"] = target
            if service_data:
                payload["service_data"] = service_data
            await ws.send_json(payload)
            response = await ws.receive_json()
            if not response.get("success", False):
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
                    self._ha_connected = True
                    self._last_error = None
                    backoff = 1
                    await ws.send_json({"id": 1, "type": "subscribe_events", "event_type": "state_changed"})
                    await ws.receive_json()
                    await ws.send_json({"id": 2, "type": "subscribe_events", "event_type": "knx_event"})
                    await ws.receive_json()
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
                    "command": "/command",
                }
            )

        async def events(request: web.Request) -> web.Response:
            limit = int(request.query.get("limit", "200") or 200)
            event_type = request.query.get("type", "").strip()
            items = self.snapshot(limit=limit)
            if event_type:
                items = [item for item in items if item["event_type"] == event_type]
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

        async def cors_options(_: web.Request) -> web.Response:
            return web.Response(status=204)

        app.add_routes(
            [
                web.get("/", root),
                web.get("/health", health),
                web.get("/events", events),
                web.post("/command", command),
                web.options("/health", cors_options),
                web.options("/events", cors_options),
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
