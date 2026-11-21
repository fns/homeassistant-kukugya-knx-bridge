# Kukugya Home Assistant KNX Bridge

Home Assistant add-on repository for the Kukugya KNX bridge.

## Current add-on version

`0.1.18`

## What is inside

- `kukugya_knx_bridge/` - the add-on source
- `repository.yaml` - Home Assistant add-on repository metadata

## Purpose

This add-on bridges Kukugya and a live KNX project through Home Assistant:

- subscribes to Home Assistant `state_changed` events
- subscribes to Home Assistant `knx_event` events
- exposes a small bridge API for Kukugya
- relays KNX control/service calls through Home Assistant
