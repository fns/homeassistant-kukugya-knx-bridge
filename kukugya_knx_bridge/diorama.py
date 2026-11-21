"""Generates a native Home Assistant Lovelace "Kukugya Diorama" dashboard from a
Kukugya diorama export (see apps/web/src/domain/services/dioramaExport.ts),
rendered with the vendored ha-diorama custom card (static/ha-diorama/card.js - see
static/ha-diorama/README.md for the exact vendored version, its documented config
schema, and how to update it).

Replaces the earlier `floorplan.py` (hand-rolled 2D SVG + ha-floorplan card) - per
explicit user decision: ha-diorama is an actively maintained, polished 3D isometric
card whose config schema (its own src/types.ts CardConfig/RoomConfig/DeviceConfig) is
explicitly meant to be generated programmatically (the project ships its own
scripts/demoflat.ts doing exactly that), so this module only needs to translate
Kukugya's already-computed room/device geometry into that schema - no custom
rendering of our own at all, unlike floorplan.py's hand-built SVG.

This module only builds pure data (the CardConfig dict) and handles local storage of
the latest import - it does not open any network/websocket connection itself.
bridge.py's own HTTP routes and HA websocket helpers (same authenticated connection
already used for live KNX state) call into this module and do the actual networking,
mirroring how _ha_call_service already works there.

One real schema constraint worth remembering: ha-diorama's own RoomConfig.points
convention is "x grows to the right, y grows UPWARD on the plan" (a math/Cartesian
y-up convention) - Kukugya's own canvas is screen/Konva y-DOWN, so
dioramaExport.ts already negates y at export time (positions and rotations alike).
This module must NOT negate/recompute anything; it just passes the already-converted
meters/degrees straight through.

dioramaExport.ts also auto-picks a `decorations` entry per device (lamp/plug/
thermostat/cover, from Device.lightType/wallPlacement and the predicted HA domain)
and per real door/window leaf on a Kukugya WallOpening - one sensible catalog
default per type, not a blind guess, per explicit user direction. Kukugya's own
per-room/wall ceiling height has nowhere to go here: ha-diorama's ceiling height is
a fixed theme constant with no per-room override in its schema. Kukugya's generic
"Objects" layer (furniture/equipment boxes) is deliberately NOT exported either -
it only carries a free-text name and raw box dimensions, no finite type enum to
map onto ha-diorama's furniture catalog with any confidence.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DATA_DIR = Path("/data/diorama")

DASHBOARD_URL_PATH = "kukugya-diorama"
DASHBOARD_TITLE = "Kukugya Diorama"
RESOURCE_PATH = "/static/ha-diorama/card.js"


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


def build_card_config(building: dict[str, Any]) -> dict[str, Any]:
    """One ha-diorama CardConfig per Kukugya building - the schema has no concept of
    multiple separate buildings in one card, so each building gets its own Lovelace
    view (see build_dashboard_views), same one-view-per-unit pattern the earlier
    floorplan.py used per floor.
    """
    floors = [
        {"id": floor["id"], "name": floor.get("name") or floor["id"], "level": floor["level"]}
        for floor in building.get("floors", [])
    ]
    rooms = [
        {
            "id": room["id"],
            "floor_id": room["floorId"],
            "name": room.get("name") or room["id"],
            "points": [[pt[0], pt[1]] for pt in room.get("points", [])],
        }
        for room in building.get("rooms", [])
        if room.get("points")
    ]
    devices = [
        {
            "entity_id": device["entityId"],
            "room": device["roomId"],
            "position": [device["position"][0], device["position"][1]],
            **({"decorations": device["decorations"]} if device.get("decorations") else {}),
        }
        for device in building.get("devices", [])
    ]
    # One DecorationConfig per auto-picked 3D prop (device lamps/plugs/thermostats/
    # covers and door/window leaves from Kukugya's own WallOpening data) - see
    # dioramaExport.ts's resolveLightDecoration/DOMAIN_DECORATION_KIND/
    # classifyOpeningKind for how each one's kind/rotation/params was picked.
    # rotation/variant/params are only present on the TS side when there was real
    # data to set them from, so they're dropped here rather than forwarded as null.
    decorations = [
        {
            "id": decoration["id"],
            "kind": decoration["kind"],
            "room": decoration["room"],
            "position": [decoration["position"][0], decoration["position"][1]],
            **({"rotation": decoration["rotation"]} if decoration.get("rotation") is not None else {}),
            **({"variant": decoration["variant"]} if decoration.get("variant") else {}),
            **({"params": decoration["params"]} if decoration.get("params") else {}),
        }
        for decoration in building.get("decorations", [])
    ]
    return {
        "type": "custom:diorama-card",
        # Splits the diorama (2/3 width) from a tile panel (1/3), grouped by room -
        # the closest built-in equivalent to ha-floorplan's old "every entity reachable
        # somewhere" requirement, since a device with no 3D decoration yet still shows
        # up here.
        "side_panel": True,
        "floors": floors,
        "rooms": rooms,
        "devices": devices,
        "decorations": decorations,
    }


def build_dashboard_views(config: dict[str, Any]) -> list[dict[str, Any]]:
    views: list[dict[str, Any]] = []
    for building in config.get("buildings", []):
        if not building.get("devices"):
            continue
        card = build_card_config(building)
        title = building.get("name") or "Building"
        views.append({"title": title, "path": _safe_id(building["id"]), "type": "panel", "cards": [card]})
    return views
