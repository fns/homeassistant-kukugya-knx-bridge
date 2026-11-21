# Vendored: ha-diorama

Source: https://github.com/CarlesRojas/ha-diorama
Vendored release: **v1.11.1** (`card.js`, downloaded from the GitHub release's own
`browser_download_url`, not rebuilt from source).
License: MIT (`LICENSE` in this folder, copied verbatim from the same tag).

Lovelace card type: `custom:diorama-card` (confirmed via the literal `"diorama-card"`
string present in the bundle, and via the project's own documented example dashboard
YAML at `ha-demo/config/diorama.yaml` in the source repo).

This replaces the earlier vendored `ha-floorplan` (SVG-based 2D floorplan card) - per
explicit user decision, since ha-diorama renders an actively-maintained, polished 3D
isometric model instead of a hand-rolled flat SVG, and its config schema
(`src/types.ts`'s `CardConfig`/`RoomConfig`/`DeviceConfig`) is explicitly designed to
be generated programmatically (the project's own `scripts/demoflat.ts` does exactly
that from a typed plan object) rather than hand-authored only through its GUI editor.

This add-on serves `card.js` directly (see `bridge.py`'s static route for
`/static/ha-diorama/card.js`) and registers it as a Home Assistant Lovelace resource
via the `lovelace/resources/create` WebSocket call, so installing/updating this
add-on is the only step required - no HACS, no manual frontend resource install.

## Config schema notes (from reading ha-diorama's own `src/types.ts`)

- `RoomConfig.points`: `[x, y][]` in **meters**, "x grows to the right, y grows
  **upward** on the plan" - Kukugya's own canvas uses screen/Konva y-DOWN convention,
  so every y coordinate must be negated (and divided by the floor's `pxPerM`) when
  converting, or rooms render mirrored vertically.
- `DeviceConfig`: `{entity_id, room: <room id>, position: [x, y]}` in the SAME
  floor-global meter space as room points (not room-relative) - `decorations` (which
  3D furniture/lamp model represents the device) is deliberately left unset by our
  export; Kukugya has no data to pick one from its own catalog, so the device still
  gets a correct room+position+entity binding but needs a one-time manual decoration
  pick in ha-diorama's own editor to actually show a 3D object.
- `FloorConfig.level`: 0 = ground floor, 1 = the one above it, -1 = a basement -
  assigned from the building's own floor order, not anything Kukugya stores directly.
- No explicit door/window "opening" concept exists in this schema at all - ha-diorama
  derives walkable passages between rooms from polygon adjacency itself
  (`src/geometry/passages.ts`), so Kukugya's own opening data is NOT exported here.

## Updating

This is a deliberate, manual action, not automated:
1. Check https://github.com/CarlesRojas/ha-diorama/releases for a newer tag.
2. Download that tag's `card.js` asset and replace the file in this folder.
3. Update the `LICENSE` file from the same tag.
4. Update the version noted above, and bump this add-on's own `ADDON_VERSION` +
   `CHANGELOG.md` entry to record the bundled card version bump.
5. Re-check `src/types.ts` for schema changes before assuming `diorama.py`'s generator
   still produces a valid config.
