"""Generates a native Home Assistant Lovelace "Kukugya Floorplan" dashboard from a
Kukugya floorplan-dashboard export (see apps/web/src/domain/services/
floorplanDashboardConfig.ts), rendered with the vendored ha-floorplan custom card
(static/ha-floorplan/floorplan.js - see static/ha-floorplan/README.md for the exact
vendored version and how to update it).

This module only builds pure data (SVG markup, card config dicts) and handles local
storage of the latest import - it does not open any network/websocket connection
itself. bridge.py's own HTTP routes and HA websocket helpers (same authenticated
connection already used for live KNX state) call into this module and do the actual
networking, mirroring how _ha_call_service already works there.

Card schema confirmed by reading ha-floorplan v1.1.5's own TypeScript source
(src/components/floorplan-card/floorplan-card.ts registers @customElement('floorplan-
card'), so the Lovelace card type is "custom:floorplan-card"; .../floorplan/lib/
floorplan-config.ts defines FloorplanConfig/FloorplanRuleConfig) rather than assumed:
  - config.image must contain the literal substring ".svg" (case-insensitive) for
    floorplan-element.ts's loadImage() to inline-parse it into the DOM (the isSvg
    check) instead of embedding it as an opaque raster <image> - inlining is required
    for per-element entity bindings to work, which is why each floor's SVG is served
    from a real ".../floor.svg" URL rather than passed as a data: URI.
  - config.rules[].entities[].element binds one HA entity to one SVG element by its
    literal `id` attribute.
  - config.rules[].state_action accepts {service, service_data}; service_data can be
    a JS template string evaluated against `entity.state` (confirmed from
    ha-floorplan's own published example: '${(entity.state === "on") ? ... }').

The exact HA Core websocket message shapes used to push this into a real Lovelace
dashboard (lovelace/resources/create, lovelace/dashboards/create,
lovelace/config/save) were cross-checked against Home Assistant core's own
homeassistant/components/lovelace/{const,resources,dashboard}.py source (field names:
res_type/url for resources; title/url_path/icon/show_in_sidebar for dashboards;
url_path/config for config/save) - but there is no live Home Assistant instance in
this repo's sandbox to exercise them against, so treat this as a protocol-conformance
best effort, not a guaranteed-correct integration, until verified against a real
install.
"""
from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

DATA_DIR = Path("/data/floorplan")

# Mirrors apps/web/src/domain/services/homeAssistantExport.ts's HA_EXPORT_DOMAINS.
GLOW_DOMAINS = {"light", "switch", "fan", "binary_sensor", "cover"}
TEXT_DOMAINS = {"sensor", "weather"}

DASHBOARD_URL_PATH = "kukugya-floorplan"
DASHBOARD_TITLE = "Kukugya Floorplan"
RESOURCE_PATH = "/static/ha-floorplan/floorplan.js"

FLOORPLAN_STYLE = """
    .kg-room { fill: #26312b; stroke: #44503f; stroke-width: 3; }
    .kg-opening { fill: #0f1a14; stroke: none; }
    .kg-device circle { stroke: #10140f; stroke-width: 2; transition: filter .2s ease, opacity .2s ease; }
    .kg-device text { font-family: sans-serif; font-size: 13px; font-weight: 700; text-anchor: middle; dominant-baseline: central; pointer-events: none; }
    .device-on circle { filter: drop-shadow(0 0 6px currentColor); }
    .device-off circle { opacity: .55; }
"""


def _safe_id(value: str) -> str:
    return "".join(c for c in str(value) if c.isalnum() or c in "-_") or "x"


def storage_path(project_id: str) -> Path:
    return DATA_DIR / f"{_safe_id(project_id)}.json"


def store_import(project_id: str, config: dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    storage_path(project_id).write_text(json.dumps(config), encoding="utf-8")


def load_import(project_id: str) -> dict[str, Any] | None:
    path = storage_path(project_id)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def find_floor(config: dict[str, Any], floor_id: str) -> dict[str, Any] | None:
    for floor in config.get("floors", []):
        if floor.get("id") == floor_id:
            return floor
    return None


def _polygon_points(polygon: list[dict[str, float]]) -> str:
    return " ".join(f"{p['x']:.1f},{p['y']:.1f}" for p in polygon)


def _rect_points(rect_points: list[float]) -> str:
    pairs = list(zip(rect_points[0::2], rect_points[1::2]))
    return " ".join(f"{x:.1f},{y:.1f}" for x, y in pairs)


def build_floor_svg(floor: dict[str, Any]) -> str:
    """One self-contained SVG per floor: room polygons, opening gaps, and one marker
    group per device (id="device-<id>") that ha-floorplan binds HA entities to by id.
    Deliberately no floorplan photo/scan background (pure vector), per the project's
    design decision - see project_ha_lovelace_dashboard_export.md.
    """
    rooms = floor.get("rooms", [])
    openings = floor.get("openings", [])
    devices = floor.get("devices", [])

    xs: list[float] = []
    ys: list[float] = []
    for room in rooms:
        for point in room.get("polygon", []):
            xs.append(point["x"])
            ys.append(point["y"])
    for device in devices:
        xs.append(device["x"])
        ys.append(device["y"])
    if not xs or not ys:
        xs, ys = [0.0, 100.0], [0.0, 100.0]
    pad = 40.0
    min_x, max_x = min(xs) - pad, max(xs) + pad
    min_y, max_y = min(ys) - pad, max(ys) + pad
    width = max(1.0, max_x - min_x)
    height = max(1.0, max_y - min_y)

    parts: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{min_x:.1f} {min_y:.1f} {width:.1f} {height:.1f}">',
        f"<style>{FLOORPLAN_STYLE}</style>",
    ]
    for room in rooms:
        points = _polygon_points(room.get("polygon", []))
        if not points:
            continue
        room_id = html.escape(_safe_id(room["id"]), quote=True)
        parts.append(f'<polygon id="room-{room_id}" class="kg-room" points="{points}" />')
    for opening in openings:
        points = _rect_points(opening.get("rectPoints", []))
        if not points:
            continue
        parts.append(f'<polygon class="kg-opening" points="{points}" />')
    device_radius = 14
    for device in devices:
        device_id = html.escape(_safe_id(device["id"]), quote=True)
        bg = html.escape(str(device.get("colorBg") or "#888888"), quote=True)
        fg = html.escape(str(device.get("colorFg") or "#ffffff"), quote=True)
        icon = html.escape(str(device.get("icon") or "")[:2])
        x, y = float(device["x"]), float(device["y"])
        parts.append(
            f'<g id="device-{device_id}" class="kg-device device-off" style="color:{bg}">'
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{device_radius}" fill="{bg}" />'
            f'<text x="{x:.1f}" y="{y:.1f}" fill="{fg}">{icon}</text>'
            f"</g>"
        )
    parts.append("</svg>")
    return "".join(parts)


def _state_action_for_domain(domain: str) -> dict[str, Any] | None:
    # Visual-only styling rules (glow when "on"/"open", dim otherwise; show the raw
    # value as text for plain sensors). Every entity still falls back to the card's
    # own `defaults.tap_action: more-info`, Home Assistant's own built-in entity
    # dialog, for actual control - see this module's docstring for why that was
    # chosen over hand-rolling per-domain call-service tap actions.
    if domain in GLOW_DOMAINS:
        return {
            "service": "floorplan.class_set",
            "service_data": '${(entity.state === "on" || entity.state === "open") ? "device-on" : "device-off"}',
        }
    if domain in TEXT_DOMAINS:
        return {
            "service": "floorplan.text_set",
            "service_data": "${entity.state !== undefined ? entity.state : \"\"}",
        }
    return None


def build_floor_card_config(floor: dict[str, Any], svg_url: str) -> dict[str, Any]:
    rules: list[dict[str, Any]] = []
    for device in floor.get("devices", []):
        element_id = f"device-{_safe_id(device['id'])}"
        for entity in device.get("entities", []):
            domain = str(entity.get("domain") or "")
            entity_id = str(entity.get("entityId") or "")
            if not entity_id:
                continue
            rule: dict[str, Any] = {"entities": [{"entity": entity_id, "element": element_id}]}
            state_action = _state_action_for_domain(domain)
            if state_action:
                rule["state_action"] = state_action
            rules.append(rule)
    return {
        "type": "custom:floorplan-card",
        "title": floor.get("name") or "Floor",
        "config": {
            "image": svg_url,
            "defaults": {"hover_action": "hover-info", "tap_action": "more-info"},
            "rules": rules,
        },
    }


def build_dashboard_views(config: dict[str, Any], svg_url_for_floor) -> list[dict[str, Any]]:
    """svg_url_for_floor: Callable[[floor_id: str], str] - kept as a callback rather
    than a plain base-url string so bridge.py can decide the exact served path
    without this module needing to know its own route layout.
    """
    views: list[dict[str, Any]] = []
    for floor in config.get("floors", []):
        if not floor.get("devices"):
            continue
        card = build_floor_card_config(floor, svg_url_for_floor(floor["id"]))
        views.append({"title": floor.get("name") or "Floor", "path": _safe_id(floor["id"]), "cards": [card]})
    return views
