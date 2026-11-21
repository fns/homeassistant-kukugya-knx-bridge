# Vendored: ha-floorplan

Source: https://github.com/ExperienceLovelace/ha-floorplan
Vendored release: **v1.1.5** (`floorplan.js`, downloaded from the GitHub release's own
`browser_download_url`, not rebuilt from source).
License: Apache License 2.0 (`LICENSE` in this folder, copied verbatim from the same tag).

This add-on serves `floorplan.js` directly (see `bridge.py`'s static route for
`/static/ha-floorplan/floorplan.js`) and registers it as a Home Assistant Lovelace
resource via the `lovelace/resources/create` WebSocket call, so installing/updating
this add-on is the only step required — no HACS, no manual frontend resource install.

## Updating

This is a deliberate, manual action, not automated:
1. Check https://github.com/ExperienceLovelace/ha-floorplan/releases for a newer tag.
2. Download that tag's `floorplan.js` asset and replace the file in this folder.
3. Update the `LICENSE` file from the same tag (Apache-2.0 terms rarely change, but keep
   the copy in sync regardless).
4. Update the version noted above, and bump this add-on's own `ADDON_VERSION` +
   `CHANGELOG.md` entry to record the bundled card version bump.
5. Re-run the floorplan dashboard push from Kukugya once to confirm the Lovelace
   resource re-registers against the new file (cache-bust via the URL's own version
   query param — see `floorplan.py`).
