# Kukugya KNX Bridge

Home Assistant add-on scaffold for the future Kukugya <-> live KNX bridge.

## Purpose

This add-on is meant to:

- connect to the Home Assistant WebSocket API
- subscribe to `state_changed` and `knx_event`
- expose a small HTTP API that Kukugya can consume
- later become the gateway for:
  - live device state visualization
  - KNX group monitor events
  - device control via Home Assistant services

## Current status

This is the first scaffold only:

- add-on manifest is in place
- bridge process skeleton is in place
- websocket/event/service-call flow is defined
- follow-up work will wire the Kukugya UI to this bridge

## Intended runtime

- runs as a Home Assistant add-on on the HA Green
- talks to the local Home Assistant core websocket endpoint
- receives the supervisor token from the add-on runtime
- serves a small LAN-accessible API on port `8099`
