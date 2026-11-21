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
  - config.rules[].state_action accepts {service, service_data}; when service_data is
    an OBJECT, ha-floorplan's own getServiceData() evaluates EVERY key through the
    same `${...}` template engine individually (confirmed by reading
    floorplan-element.ts's getServiceData), not just a single top-level string - this
    is what lets floorplan.text_set target a specific element id (service_data.element,
    a plain literal, left untouched by the evaluator) with a computed value
    (service_data.text, a real `${entity.state...}` template) in the same call.

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
import re
from pathlib import Path
from typing import Any

DATA_DIR = Path("/data/floorplan")

# Mirrors apps/web/src/domain/services/homeAssistantExport.ts's HA_EXPORT_DOMAINS.
GLOW_DOMAINS = {"light", "switch", "fan", "binary_sensor", "cover"}
TEXT_DOMAINS = {"sensor", "weather"}

DASHBOARD_URL_PATH = "kukugya-floorplan"
DASHBOARD_TITLE = "Kukugya Floorplan"
RESOURCE_PATH = "/static/ha-floorplan/floorplan.js"

FONT_STACK = '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif'

FLOORPLAN_STYLE = f"""
    .kg-room {{ fill: #3c4a3f; stroke: none; }}
    .kg-wall {{ stroke: #5a6b5d; stroke-width: 3; stroke-linecap: round; stroke-linejoin: round; fill: none; }}
    .kg-opening {{ fill: #1a241c; stroke: none; }}
    .kg-device rect {{ stroke: #353535; transition: filter .2s ease, opacity .2s ease; }}
    .kg-device text {{ font-family: {FONT_STACK}; font-weight: 700; pointer-events: none; }}
    .device-on rect {{ filter: drop-shadow(0 0 9px currentColor) brightness(1.2); opacity: 1; }}
    .device-off rect {{ opacity: .4; filter: grayscale(70%); }}
    .kg-device-unmatched rect {{ stroke: #e05d44; stroke-width: 2.5; stroke-dasharray: 4 3; }}
    .kg-unmatched-badge circle {{ fill: #e05d44; stroke: #1c2a20; stroke-width: 1.5; }}
    .kg-unmatched-badge text {{ font-family: {FONT_STACK}; font-size: 10px; font-weight: 800; fill: #fff; pointer-events: none; }}
    .kg-badge rect {{ fill: #1c2a20dd; stroke: #5a6b5d; stroke-width: 1; }}
    .kg-badge text {{ font-family: {FONT_STACK}; font-size: 10px; font-weight: 600; fill: #d7ddd0; pointer-events: none; }}
"""

# Mirrors DeviceLayer.tsx's own baseline icon box (32x24 px at ratio=1) and its
# ICON_WIDTH_MIN_M/ICON_WIDTH_MAX_M clamp range exactly - this is the whole point of
# this round's work ("nézzen ki pont ugyanúgy, mint a Kukugya canvason").
ICON_WIDTH_MIN_M = 1 / 12
ICON_WIDTH_MAX_M = 0.72
BASELINE_ICON_WIDTH_PX = 32.0
BASELINE_ICON_HEIGHT_PX = 24.0

UNMATCHED_BADGE_RADIUS = 7
SENSOR_BADGE_HEIGHT = 18
SENSOR_BADGE_GAP = 4

# A sensor's HA name carries its token as a "(Temperature)"-style suffix (see
# buildHaEntityName's `suffix` parameter, apps/web/src/editor/EditorShell.tsx) when a
# device exposes more than one sensor token - used here purely for a short label and a
# width that's reasonable for that token's typical value length, not pixel-perfect
# auto-fit (plain SVG has no reliable way to auto-size a rect to live-updating sibling
# text without JS we don't control the runtime of).
SENSOR_BADGE_RULES: list[tuple[re.Pattern, str, int]] = [
    (re.compile(r"\(Temperature\)\s*$", re.I), "T", 46),
    (re.compile(r"\(Humidity\)\s*$", re.I), "H", 42),
    (re.compile(r"\(CO2\)\s*$", re.I), "CO2", 54),
    (re.compile(r"\(VOC\)\s*$", re.I), "VOC", 54),
    (re.compile(r"\(Power\)\s*$", re.I), "P", 56),
    (re.compile(r"\(Energy\)\s*$", re.I), "E", 56),
    (re.compile(r"\(Pressure\)\s*$", re.I), "PA", 50),
    (re.compile(r"\(Brightness\)\s*$", re.I), "LX", 50),
]


def _sensor_badge_spec(entity: dict[str, Any]) -> tuple[str, int]:
    name = str(entity.get("name") or "")
    for pattern, prefix, width in SENSOR_BADGE_RULES:
        if pattern.search(name):
            return prefix, width
    if str(entity.get("domain") or "") == "weather":
        return "WX", 44
    return "", 38


def _estimate_label_width(text: str, font_size: float) -> float:
    # Matches DeviceLayer.tsx's own estimateLabelWidth() character-count heuristic
    # exactly (it has no real text-measurement API available either, for the same
    # reason we don't: this has to work before the font has necessarily loaded/laid
    # out at all).
    return len(text) * font_size * 0.65 + font_size


def _device_icon_metrics(floor: dict[str, Any], device: dict[str, Any]) -> dict[str, float]:
    """Reproduces DeviceLayer.tsx's useMemo(iconMetrics) + its `deviceIconWidth`
    call site exactly, so a device renders at the SAME box size/corner radius/font
    size/stroke width here as it does on the real Kukugya canvas - same floor
    pxPerM, same floor iconDensityPerM, same formula, same baseline 32x24 box.
    """
    px_per_m = float(floor.get("pxPerM") or 75.0)
    density = float(floor.get("iconDensityPerM") or 5.0)
    icon_width_m = max(ICON_WIDTH_MIN_M, min(ICON_WIDTH_MAX_M, 1.0 / density))
    icon_width = icon_width_m * px_per_m
    icon_height = icon_width * (BASELINE_ICON_HEIGHT_PX / BASELINE_ICON_WIDTH_PX)
    ratio = icon_width / BASELINE_ICON_WIDTH_PX
    icon_font_size = 10.0 * ratio
    icon_corner = 4.0 * ratio
    stroke_width = 1.1 * ratio
    label = str(device.get("icon") or "?")
    device_icon_width = max(icon_width, _estimate_label_width(label, icon_font_size))
    return {
        "width": device_icon_width,
        "height": icon_height,
        "fontSize": icon_font_size,
        "corner": icon_corner,
        "strokeWidth": stroke_width,
    }


def _safe_id(value: str) -> str:
    return "".join(c for c in str(value) if c.isalnum() or c in "-_") or "x"


def _badge_element_id(entity_id: str) -> str:
    # _safe_id alone would just DROP the "." separating domain from slug (it only
    # keeps alnum/-/_), collapsing e.g. "sensor.study_temp" into "sensorstudy_temp" -
    # replace it with "_" first so the id stays readable and collision-free.
    return f"badge-{_safe_id(str(entity_id).replace('.', '_'))}"


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


def _device_tooltip_text(device: dict[str, Any], known_entity_ids: set[str] | None) -> str:
    """Native SVG <title> hover tooltip content - deliberately NOT built via
    ha-floorplan's own hover_action: "hover-info" (which would overwrite this same
    <title> element's text with just the HA entity's own state/attributes, clobbering
    the group-address list below) - see build_floor_card_config's own comment on why
    hover_action is left unset.
    """
    lines: list[str] = []
    human_id = str(device.get("humanId") or "").strip()
    name = str(device.get("name") or "").strip()
    header = f"L.{human_id}" if human_id else "Device"
    if name:
        header = f"{header} - {name}"
    lines.append(header)

    entities = device.get("entities", [])
    if entities:
        lines.append("")
        lines.append("Home Assistant:")
        for entity in entities:
            entity_id = str(entity.get("entityId") or "")
            unmatched = known_entity_ids is not None and entity_id not in known_entity_ids
            lines.append(f"  {entity_id}{' (not found)' if unmatched else ''}")

    group_addresses = device.get("groupAddresses", [])
    if group_addresses:
        lines.append("")
        lines.append("Group addresses:")
        for ga in group_addresses:
            ga_type = str(ga.get("type") or "").strip()
            lines.append(f"  {ga.get('main')}/{ga.get('middle')}/{ga.get('addr')}{(' ' + ga_type) if ga_type else ''}")

    return "\n".join(lines)


def build_floor_svg(floor: dict[str, Any], known_entity_ids: set[str] | None = None) -> str:
    """One self-contained SVG per floor: room polygons, opening gaps, and one marker
    group per device (id="device-<id>") that ha-floorplan binds HA entities to by id.
    Deliberately no floorplan photo/scan background (pure vector), per the project's
    design decision - see project_ha_lovelace_dashboard_export.md.

    known_entity_ids: the set of entity_ids that actually exist in Home Assistant right
    now (fetched live via `get_states` over the same HA websocket connection used
    elsewhere in bridge.py) - None means "unknown" (e.g. HA unreachable), in which case
    no device is flagged as unmatched rather than flagging everything.
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
    # Extra bottom padding so a device near the floor's edge still has room for its
    # sensor-value badge row underneath without it getting clipped by the viewBox.
    pad = 40.0
    bottom_pad = pad + SENSOR_BADGE_HEIGHT + 20.0
    min_x, max_x = min(xs) - pad, max(xs) + pad
    min_y, max_y = min(ys) - pad, max(ys) + bottom_pad
    width = max(1.0, max_x - min_x)
    height = max(1.0, max_y - min_y)

    parts: list[str] = [
        # width/height="100%" is required - ha-floorplan's own CSS (floorplan-element.ts) only
        # flex-stretches the SVG's immediate container, not a plain inline <svg> that has no
        # explicit size of its own; without these, the browser falls back to the standard
        # replaced-element default box (a small fixed size) regardless of the viewBox, which is
        # why the floorplan rendered as a tiny box instead of filling the card.
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="100%" height="100%" '
            f'preserveAspectRatio="xMidYMid meet" '
            f'viewBox="{min_x:.1f} {min_y:.1f} {width:.1f} {height:.1f}">'
        ),
        f"<style>{FLOORPLAN_STYLE}</style>",
    ]
    for room in rooms:
        points = _polygon_points(room.get("polygon", []))
        if not points:
            continue
        room_id = html.escape(_safe_id(room["id"]), quote=True)
        parts.append(f'<polygon id="room-{room_id}" class="kg-room" points="{points}" />')
    for room in rooms:
        # Wall centerlines are drawn separately from the room fill above (not as the
        # polygon's own stroke) - floorplanDashboardConfig.ts already cut out the span
        # of every floor-to-ceiling opening, so a missing piece here means a real
        # absence of wall, not a rendering gap to "fix".
        for segment in room.get("wallSegments", []):
            start, end = segment["start"], segment["end"]
            parts.append(
                f'<line class="kg-wall" x1="{start["x"]:.1f}" y1="{start["y"]:.1f}" '
                f'x2="{end["x"]:.1f}" y2="{end["y"]:.1f}" />'
            )
    for opening in openings:
        points = _rect_points(opening.get("rectPoints", []))
        if not points:
            continue
        parts.append(f'<polygon class="kg-opening" points="{points}" />')

    for device in devices:
        device_id = html.escape(_safe_id(device["id"]), quote=True)
        bg = html.escape(str(device.get("colorBg") or "#888888"), quote=True)
        fg = html.escape(str(device.get("colorFg") or "#ffffff"), quote=True)
        icon = html.escape(str(device.get("icon") or "?"))
        x, y = float(device["x"]), float(device["y"])
        entities = device.get("entities", [])
        has_unmatched = known_entity_ids is not None and any(
            str(e.get("entityId") or "") not in known_entity_ids for e in entities
        )
        marker_class = "kg-device device-off" + (" kg-device-unmatched" if has_unmatched else "")
        tooltip = html.escape(_device_tooltip_text(device, known_entity_ids))
        metrics = _device_icon_metrics(floor, device)
        box_w, box_h = metrics["width"], metrics["height"]
        box_x, box_y = x - box_w / 2, y - box_h / 2

        parts.append(f'<g id="device-{device_id}" class="{marker_class}" style="color:{bg}">')
        parts.append(f"<title>{tooltip}</title>")
        # Same shape/metrics as DeviceLayer.tsx's own device icon (rounded rect, not a
        # circle) - box size, corner radius, stroke width, and font size all come from
        # the exact same iconWidthM/iconDensityPerM/pxPerM formula as the real canvas.
        parts.append(
            f'<rect x="{box_x:.1f}" y="{box_y:.1f}" width="{box_w:.1f}" height="{box_h:.1f}" '
            f'rx="{metrics["corner"]:.1f}" fill="{bg}" stroke-width="{metrics["strokeWidth"]:.2f}" />'
        )
        # text-anchor is set as a direct SVG attribute (not only via CSS) so
        # horizontal centering can never be lost to a cascade/scoping surprise;
        # dy="0.35em" (not CSS dominant-baseline, which renders inconsistently
        # across browsers, notably Safari/WebKit) is the standard, reliable
        # cross-browser trick for vertically centering single-line SVG text.
        parts.append(
            f'<text x="{x:.1f}" y="{y:.1f}" text-anchor="middle" dy="0.35em" '
            f'font-size="{metrics["fontSize"]:.1f}" fill="{fg}">{icon}</text>'
        )
        if has_unmatched:
            bx, by = box_x + box_w, box_y
            parts.append(
                f'<g class="kg-unmatched-badge">'
                f'<circle cx="{bx:.1f}" cy="{by:.1f}" r="{UNMATCHED_BADGE_RADIUS}" />'
                f'<text x="{bx:.1f}" y="{by:.1f}" text-anchor="middle" dy="0.35em">!</text>'
                f"</g>"
            )
        parts.append("</g>")

        sensor_entities = [e for e in entities if str(e.get("domain") or "") in TEXT_DOMAINS]
        if sensor_entities:
            specs = [_sensor_badge_spec(e) for e in sensor_entities]
            total_width = sum(w for _, w in specs) + SENSOR_BADGE_GAP * (len(specs) - 1)
            cursor_x = x - total_width / 2
            badge_y = box_y + box_h + 10
            for entity, (prefix, badge_width) in zip(sensor_entities, specs):
                entity_id = str(entity.get("entityId") or "")
                text_id = html.escape(_badge_element_id(entity_id), quote=True)
                badge_cx = cursor_x + badge_width / 2
                badge_cy = badge_y + SENSOR_BADGE_HEIGHT / 2
                label = f"{prefix} —" if prefix else "—"
                parts.append(
                    f'<g class="kg-badge">'
                    f'<rect x="{cursor_x:.1f}" y="{badge_y:.1f}" width="{badge_width}" '
                    f'height="{SENSOR_BADGE_HEIGHT}" rx="4" />'
                    f'<text id="{text_id}" x="{badge_cx:.1f}" y="{badge_cy:.1f}" '
                    f'text-anchor="middle" dy="0.35em">{html.escape(label)}</text>'
                    f"</g>"
                )
                cursor_x += badge_width + SENSOR_BADGE_GAP
    parts.append("</svg>")
    return "".join(parts)


def _state_action_for_glow(domain: str) -> dict[str, Any] | None:
    if domain not in GLOW_DOMAINS:
        return None
    return {
        "service": "floorplan.class_set",
        "service_data": '${(entity.state === "on" || entity.state === "open") ? "device-on" : "device-off"}',
    }


def _state_action_for_sensor(entity: dict[str, Any]) -> dict[str, Any]:
    # Targets the sensor's OWN badge <text> element (service_data.element), separate
    # from the device marker circle - unlike the glow rule above, which implicitly
    # targets whatever element the rule's own `entities[].element` points at.
    prefix, _ = _sensor_badge_spec(entity)
    entity_id = str(entity.get("entityId") or "")
    label_prefix = json.dumps(f"{prefix} " if prefix else "")
    return {
        "service": "floorplan.text_set",
        "service_data": {
            "element": _badge_element_id(entity_id),
            "text": f"${{entity.state !== undefined ? {label_prefix} + entity.state : '—'}}",
        },
    }


def build_floor_card_config(floor: dict[str, Any], svg_url: str, title: str | None = None) -> dict[str, Any]:
    rules: list[dict[str, Any]] = []
    for device in floor.get("devices", []):
        element_id = f"device-{_safe_id(device['id'])}"
        for entity in device.get("entities", []):
            domain = str(entity.get("domain") or "")
            entity_id = str(entity.get("entityId") or "")
            if not entity_id:
                continue
            rule: dict[str, Any] = {"entities": [{"entity": entity_id, "element": element_id}]}
            if domain in TEXT_DOMAINS:
                rule["state_action"] = _state_action_for_sensor(entity)
            else:
                glow_action = _state_action_for_glow(domain)
                if glow_action:
                    rule["state_action"] = glow_action
            rules.append(rule)
    return {
        "type": "custom:floorplan-card",
        "title": title or floor.get("name") or "Floor",
        # full_height is a TOP-LEVEL card field (FloorplanCard.isFullHeight reads
        # this.config.full_height, where this.config is the whole card dict, not the
        # nested floorplan `config:` block) - without it the card only takes its
        # content's natural height, leaving most of the view visually empty.
        "full_height": True,
        "config": {
            "image": svg_url,
            # Deliberately NOT "hover_action: hover-info" - ha-floorplan's own hover-info
            # action overwrites the SVG element's <title> text with just the entity's
            # state/attributes (floorplan-element.ts's handleEntitySetHoverOver sets
            # `titleElement.textContent = ...` unconditionally), which would clobber the
            # group-address list build_floor_svg already bakes into that same <title>.
            # Leaving hover_action unset means ha-floorplan never touches it, and the
            # browser's own native SVG title-hover tooltip shows our static text as-is.
            # log_level/console_log_level are also deliberately absent: ha-floorplan has
            # no runtime on/off control for its own debug console (it's a static,
            # init-time-only setting), and the "not found" badge now baked directly onto
            # the marker (see build_floor_svg) replaces most of what the log was for.
            "defaults": {"tap_action": "more-info"},
            "rules": rules,
        },
    }


def build_dashboard_views(config: dict[str, Any], svg_url_for_floor) -> list[dict[str, Any]]:
    """svg_url_for_floor: Callable[[floor_id: str], str] - kept as a callback rather
    than a plain base-url string so bridge.py can decide the exact served path
    without this module needing to know its own route layout.
    """
    included = [floor for floor in config.get("floors", []) if floor.get("devices")]

    views: list[dict[str, Any]] = []
    for floor in included:
        name = floor.get("name") or "Floor"
        building_name = floor.get("buildingName") or ""
        # Always "Building - Floor", not just when two floor names collide - the
        # building context is useful at a glance even when names are unique.
        title = f"{building_name} - {name}" if building_name else name
        card = build_floor_card_config(floor, svg_url_for_floor(floor["id"]), title)
        # "panel" makes the single card fill the entire view edge-to-edge (full width
        # and height) instead of the default masonry layout, which only gives each
        # card one narrow column and otherwise leaves the rest of the view empty -
        # exactly what each of these one-card-per-floor views needs.
        views.append({"title": title, "path": _safe_id(floor["id"]), "type": "panel", "cards": [card]})
    return views
