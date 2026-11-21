# Changelog

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
