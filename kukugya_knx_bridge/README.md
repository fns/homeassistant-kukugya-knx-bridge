# Kukugya KNX Bridge

**Version: 0.1.15**

Home Assistant add-on for the Kukugya <-> live KNX bridge.

## Purpose

This add-on is meant to:

- connect to the Home Assistant WebSocket API
- subscribe to `state_changed` and `knx_event`
- expose a small HTTP API that Kukugya can consume
- keep a current entity cache and a KNX telegram buffer
- later become the gateway for:
  - live device state visualization
  - KNX group monitor events
  - device control via Home Assistant services

## Current status

Current bridge capabilities:

- Home Assistant websocket auth and reconnect
- bridge HTTP API with bearer-token authentication
- generated or configured persistent API key
- HTTP endpoints expose:
  - `/health`
  - `/events`
  - `/entities`
  - `/entities/{entity_id}`
  - `/telegrams`
  - `/command`
  - `/snapshot`
  - `/floorplan/import` (POST) - generates/updates a real "Kukugya Floorplan" Lovelace
    dashboard (one view per floor) from a Kukugya floorplan export, using the vendored
    `ha-floorplan` custom card (see `static/ha-floorplan/README.md`)
  - `/floorplan/svg/{project_id}/{floor_id}.svg` and `/static/ha-floorplan/floorplan.js`
    - public (no bearer token), fetched directly by the browser's HA frontend

See `/addons/homeassistant-knx-bridge/CHANGELOG.md` for version history.

## Intended runtime

- runs as a Home Assistant add-on on the HA Green
- talks to the local Home Assistant core websocket endpoint
- receives the supervisor token from the add-on runtime
- serves a small LAN-accessible API on port `8099`
