# Changelog

## 0.2.0

- **Replaces the floorplan dashboard with a diorama dashboard**, per explicit user decision: the hand-rolled 2D SVG + `ha-floorplan` card is gone, replaced by the actively-maintained, polished 3D isometric [ha-diorama](https://github.com/CarlesRojas/ha-diorama) card (vendored `card.js` v1.11.1, `static/ha-diorama/`)
- new `POST /diorama/import` generates/updates a real "Kukugya Diorama" Lovelace dashboard (one 3D view per building, `type: custom:diorama-card`) directly from Kukugya's room polygons (converted to meters, y-flipped) and device positions/entity bindings - no custom SVG rendering of our own needed at all, ha-diorama's own config schema does the rest
- removed `/floorplan/import` and `/floorplan/svg/...` (and `floorplan.py` entirely) along with the vendored `ha-floorplan` card
- devices still need a one-time manual "decoration" pick (which 3D furniture/lamp model represents them) in ha-diorama's own editor - Kukugya has no catalog data to automate that part, only the room/position/entity-binding geometry

## 0.1.18

- floorplan dashboard: device markers now use the EXACT same shape/sizing as the real Kukugya canvas (`DeviceLayer.tsx`) - a rounded rect (not a circle), sized from the same `iconWidthM = clamp(1/iconDensityPerM, 1/12, 0.72)` formula × the floor's own `pxPerM`, with matching corner radius/stroke width/font size all scaled from the same `ratio`, and the full device-type icon glyph (not truncated to 2 characters)
- `floorplanDashboardConfig.ts` now exports each floor's `pxPerM` and `iconDensityPerM` so the add-on can reproduce this sizing without guessing

## 0.1.17

- floorplan dashboard visual overhaul: lighter room fill, modern font stack, stronger on/off contrast (brighter glow when on, desaturated+dimmed when off)
- device icon text now has `text-anchor="middle"` set as a direct SVG attribute (not only CSS) so horizontal+vertical centering can't be lost to any cascade/scoping surprise
- numeric sensor values (temperature/humidity/CO2/...) now render in their own small labelled pill below the device marker (`floorplan.text_set` targeting a dedicated badge element via `service_data.element`), instead of overwriting the device icon's own text
- a device with no matching Home Assistant entity now gets an obvious red "!" badge at the marker's corner, in addition to the existing dashed ring
- each floor's dashboard tab/card title always shows "Building - Floor" (previously only when two floor names collided)
- removed the forced `log_level`/`console_log_level: debug` diagnostic (no native runtime toggle exists in ha-floorplan anyway; the on-icon "not found" badge now covers what the console log was for)

## 0.1.16

- floorplan dashboard: fix device icon text not being vertically centered in its circle (cross-browser `dy="0.35em"` offset instead of CSS `dominant-baseline`, which renders inconsistently, notably in Safari)
- floorplan dashboard: a device marker whose entity_id doesn't actually exist in Home Assistant right now gets a dashed red/orange ring (`/floorplan/svg/...` fetches live entity states via `get_states` on every request, so this stays current without a full re-push)
- floorplan dashboard: hover tooltip now shows the device's full group-address list (main/middle/addr/type) alongside its Home Assistant entity_id(s) and whether each was found — `hover_action: hover-info` removed from the card defaults since it would otherwise overwrite this same tooltip with just the entity's state/attributes

## 0.1.15

- floorplan dashboard: bump the diagnostic `log_level`/`console_log_level` from `warning` to `debug` so the browser console also shows a "STATE `<entity_id>`: `<state>` (initial load)" line for every entity that bound successfully, not just "Cannot find ..." warnings for the ones that didn't

## 0.1.14

- floorplan dashboard: where an opening spans floor-to-ceiling (a real absence of wall, not a door/window), render neither the opening symbol nor the wall line for that span — wall centerlines are now computed per-room on the Kukugya export side (`floorplanDashboardConfig.ts`'s `buildWallSegmentsWithGaps`, reusing `buildRoomWallSegments`/`resolveWallHeightM`/`computeOpeningGeometry`) and drawn as separate `<line class="kg-wall">` pieces instead of the room polygon's own stroke

## 0.1.13

- floorplan dashboard: temporarily set `log_level`/`console_log_level: warning` in the generated `ha-floorplan` card config so its internal warnings (e.g. a mismatched SVG element id) actually surface in the browser console instead of being swallowed by the card's own hidden log overlay — diagnostic aid, remove once entity/click binding is confirmed solid

## 0.1.12

- floorplan dashboard: fix the floorplan rendering tiny in a mostly-empty view — the generated SVG now sets explicit `width="100%" height="100%"` (previously viewBox-only, which browsers render at a small default box when inlined), the card sets `full_height: true`, and each floor's view uses `type: "panel"` instead of masonry so the single floorplan card fills the whole view edge-to-edge

## 0.1.11

- floorplan dashboard: use "Building - Floor" as the tab title only when two floors share the same name across different buildings, otherwise keep the plain floor name

## 0.1.10

- add a floorplan-based Home Assistant dashboard generator: `POST /floorplan/import` accepts a Kukugya floorplan export and automatically creates/updates a real "Kukugya Floorplan" Lovelace dashboard (one view per floor) using the vendored `ha-floorplan` custom card, pushed via the add-on's existing authenticated Home Assistant websocket connection — no HACS install, no manual YAML paste
- serve the vendored `ha-floorplan` card and the generated per-floor SVGs publicly (no bearer token) at `/static/ha-floorplan/floorplan.js` and `/floorplan/svg/{project}/{floor}.svg`, since the browser's own HA frontend fetches these directly, not through Kukugya

## 0.1.9

- bump version (next release placeholder)

## 0.1.8

- forward `dpt_main`, `dpt_sub`, and `unit` fields from HA `knx_event` so the Kukugya monitor can decode and display values for group addresses not in the Kukugya project

## 0.1.7

- fix `knx.read`: send address as list so HA actually dispatches the GroupValueRead on the bus

## 0.1.6

- add `knx.read` command: sends a real GroupValueRead on the KNX bus and logs the outgoing telegram to the event buffer
- `knx.send` now also logs its outgoing GroupValueWrite to the event buffer so it appears in the monitor list

## 0.1.5

- add Home Assistant add-on icon and logo from Kukugya branding
- document add-on changelog and update flow
- keep bearer-token bridge authentication and generated API key support in the published add-on

## 0.1.3

- add bearer-token authentication to the bridge HTTP API
- support generated persistent API keys when `api_key` is left empty
- persist bridge URL and API key in the Kukugya project
- improve Home Assistant publish flow with automatic patch-version bumping

## 0.1.2

- expose live KNX telegram feed and entity cache over HTTP
- add Home Assistant service-call and `knx.send` command support
- add websocket auth, reconnect handling, and health reporting

## 0.1.1

- fix Home Assistant add-on build metadata and packaged dependencies
- improve compatibility with Home Assistant image build pipeline

## 0.1.0

- initial add-on scaffold
- base Docker image, run script, and bridge skeleton
- first local HTTP API surface for Kukugya integration
