# Changelog

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
