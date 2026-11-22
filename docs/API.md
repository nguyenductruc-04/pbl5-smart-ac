# Gateway REST API (v1)

Base URL: `http://gateway.local:8000/api/v1` (or `http://10.42.0.1:8000/api/v1` on the backup AP).
Interactive documentation generated from the code: `http://gateway.local:8000/docs`.

The dashboard at `http://gateway.local:8000/` is a client of this API ([ADR 0003](adr/0003-dashboard.md)).

Design rationale: [ADR 0002](adr/0002-safety-layer-and-control-api.md).

## Authentication

Every endpoint except `/health` requires the header `X-API-Key`.

| Key (`gateway/.env`) | Role | Can send commands as |
|---|---|---|
| `API_KEY` | app | `app` |
| `API_KEY_AUTOMATION` (optional) | automation | `rule`, `ai` (must set `source` in the body) |

Plain HTTP: use on the local network or over Tailscale only.

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Liveness. `503` when the gateway lost the MQTT broker. No key. |
| GET | `/policy` | Safety Layer thresholds in effect. |
| GET | `/rooms` | Known rooms and node status. |
| GET | `/rooms/{room}` | Node status, latest telemetry, expected AC state, safety timers. |
| POST | `/rooms/{room}/commands` | Send a command through the Safety Layer. |
| POST | `/rooms/{room}/commands/resend` | Send the expected state again, when the AC seems to have missed a frame (app key only). |
| PUT | `/rooms/{room}/ac-state` | Tell the gateway what the AC is really doing; nothing is sent (app key only). |
| POST | `/pairing` | Create a one-time code and QR image to sign in another device (app key only). |
| GET | `/system/network` | Pi network mode and Wi-Fi state reported by `netwatch`. |
| PUT | `/system/network` | Change the network mode: `auto`, `standalone` or `home` (app key only). |
| POST | `/pairing/claim` | Exchange a pairing code for the app key. No key needed. |
| DELETE | `/rooms/{room}/auto-hold` | Let automation resume now (app key only). |
| GET | `/rooms/{room}/telemetry?limit=&since=&until=` | Telemetry history, newest first. |
| GET | `/rooms/{room}/telemetry/series?hours=&points=` | Bucket-averaged temperature/humidity for charts, oldest first. |
| GET | `/rooms/{room}/commands?limit=` | Commands sent and their results. |
| GET | `/rooms/{room}/decisions?limit=` | Safety Layer audit log. |
| POST | `/rooms/{room}/comfort` | Record a comfort vote (app key only). |
| GET | `/rooms/{room}/comfort?limit=&since=` | Comfort votes with their context, newest first (labelled data for Milestone 6). |
| DELETE | `/rooms/{room}/comfort/{id}` | Undo a vote within 120 s (app key only). |
| GET | `/rooms/{room}/suggestion` | Advice from the personal comfort model (read only). |
| GET | `/rooms/{room}/ir-events?limit=` | Remote presses overheard by the node. |

## Sending a command

Omitted fields keep their current value; the gateway always sends the full state to the node.

```bash
curl -X POST http://gateway.local:8000/api/v1/rooms/room01/commands \
  -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
  -d '{"power": "on", "mode": "cool", "temp": 25, "fan": "auto"}'
```

| Field | Values |
|---|---|
| `power` | `on`, `off` |
| `mode` | `cool`, `dry`, `fan`, `auto`, `heat` |
| `temp` | integer °C (policy: 16–30 manual, 24–29 automatic) |
| `fan` | `auto`, `low`, `mid`, `high` |
| `source` | automation key only: `rule` or `ai` |
| `confirm` | app key only: `true` to turn on although the compressor rest period is not over (see below) |

Success (`200`):

```json
{
  "status": "executed",
  "cmd_id": "c-382d0a7c",
  "source": "app",
  "code": "OK",
  "requested": {"power": "on", "mode": "cool", "temp": 25, "fan": "auto"},
  "latency_ms": 471,
  "room": { "...": "same object as GET /rooms/{room}" }
}
```

`status` is `skipped` (with `cmd_id: null`) when an automatic command equals the current state.

### When the AC missed a command (v0.9.0, [ADR 0005](adr/0005-missed-ir-commands.md))

- **Early start.** A manual power-on during the compressor rest period returns `409 COMPRESSOR_MIN_OFF` with `"can_confirm": true`. Sending the same command with `"confirm": true` is accepted (`code: EARLY_START_CONFIRMED`). Automatic commands cannot be confirmed.
- **Resend.** `POST /rooms/{room}/commands/resend` (no body) sends the expected state again; response as above with `code: RESEND`. `409 NO_STATE` if the state was never known.
- **Sync.** `PUT /rooms/{room}/ac-state` with any of `power`, `mode`, `temp`, `fan` sets the expected state without sending IR, clears `uncertain`, starts the app auto-hold and leaves the compressor timers alone. Returns the room state; the decision log gets an entry with verdict `sync`.

## Device pairing (v0.9.0, [ADR 0006](adr/0006-field-network-and-device-pairing.md))

```bash
curl -X POST -H "X-API-Key: $API_KEY" http://gateway.local:8000/api/v1/pairing
```

```json
{"code": "pfpAF2zAXt4k7aPh", "url": "http://10.42.0.1:8000/#pair=pfpAF2zAXt4k7aPh",
 "expires_in_s": 300, "qr": "data:image/svg+xml;charset=utf-8,..."}
```

## Network mode (v0.9.0)

```bash
curl -X PUT -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
  -d '{"mode": "standalone"}' http://gateway.local:8000/api/v1/system/network
```

```json
{"mode": "standalone", "chosen": "standalone", "default": "auto",
 "status": {"mode": "auto", "state": "home", "connection": "Mai", "ap": "SmartAC-Backup", "ts": 1795290000.0, "running": true},
 "ap_ssid": "SmartAC-Backup", "ap_url": "http://10.42.0.1:8000/", "home_url": "http://gateway.local:8000/"}
```

Before answering, a change that will move the Pi between its own Wi-Fi and home Wi-Fi publishes `{"net":"backup"}` or `{"net":"home"}` (not retained) on every node's `home/{room}/config`, so nodes follow in seconds (ADR 0006).

`mode` is what `netwatch` will apply (the dashboard choice, else `NETWORK_MODE` from `.env`); `status.mode` is what it applied on its last check, so the two differ for up to 15 s after a change. `status` is `null`, or `running: false`, when `netwatch` is not running. `GET /health` also returns `time` (gateway clock, unix seconds).

## Device pairing, continued

Opening `url` on another device signs it in: the dashboard posts the code to `/pairing/claim`, which returns `{"api_key": "..."}` once. A used, unknown or expired code gives `410 PAIR_INVALID`; more than 10 failures per minute give `429 PAIR_TOO_MANY`. Codes live in RAM only and vanish when the gateway restarts.

## Errors

```json
{"error": {"code": "COMPRESSOR_MIN_OFF", "message": "...", "retry_after_s": 150}}
```

When `retry_after_s` is present the response also carries a `Retry-After` header.

| HTTP | `code` | Meaning |
|---|---|---|
| 401 | `UNAUTHORIZED` | Missing or wrong key |
| 403 | `SOURCE_NOT_ALLOWED`, `FORBIDDEN`, `CONFIRM_NOT_ALLOWED` | Key not allowed to do this |
| 404 | `ROOM_NOT_FOUND` | No node has ever reported for this room |
| 409 | `COMPRESSOR_MIN_OFF`, `COMPRESSOR_MIN_ON`, `MANUAL_HOLD`, `STATE_UNCERTAIN`, `TELEMETRY_STALE`, `ROOM_EMPTY`, `STEP_TOO_LARGE` | Rejected by the Safety Layer (`COMPRESSOR_MIN_OFF` on a manual command adds `can_confirm: true`) |
| 409 | `NO_STATE` | Nothing to resend yet |
| 410 | `PAIR_INVALID` | Pairing code used, unknown or expired |
| 422 | `TEMP_OUT_OF_RANGE`, or FastAPI validation detail | Invalid request |
| 429 | `RATE_LIMIT`, `PAIR_TOO_MANY` | Too frequent |
| 502 | `NODE_ERROR` | Node answered but could not send the IR frame |
| 503 | `NODE_OFFLINE`, `BROKER_UNAVAILABLE` | A link is down; the command was **not** queued |
| 504 | `NODE_TIMEOUT` | No answer within 5 s; the AC state is now marked uncertain |

## Comfort votes

The dashboard asks "Bạn thấy thế nào?" and records the answer together with the latest sensor readings and the expected AC state, so each vote is a self-contained training sample.

```bash
curl -X POST http://gateway.local:8000/api/v1/rooms/room01/comfort \
  -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" -d '{"vote": "cooler"}'
```

`vote` is `cooler` (wants it cooler), `comfortable` or `warmer`; stored as −1 / 0 / +1. Response `201`:

```json
{"id": 12, "ts": 1794983381.1, "vote": "cooler", "temp": 29.4, "hum": 73.2, "presence": true,
 "telemetry_age_s": 6.2, "ac_power": "on", "ac_mode": "cool", "ac_temp": 26, "ac_uncertain": false}
```

| HTTP | `code` | Meaning |
|---|---|---|
| 403 | `FORBIDDEN` | Automation key: only people vote |
| 409 | `TELEMETRY_STALE` | No reading in the last 120 s; a vote without context is not stored |
| 429 | `VOTE_TOO_FAST` | Less than 5 s since the previous vote (double tap) |
| 409 | `UNDO_EXPIRED` | Undo after 120 s |

## Suggestion

`GET /rooms/{room}/suggestion` returns the advice of the comfort model (ADR 0004). It never sends a command; `target` can be posted to `/commands` as is.

```json
{
  "action": "turn_on", "reason": "TOO_WARM",
  "target": {"power": "on", "mode": "cool", "temp": 25, "fan": "auto"},
  "room_temp": 29.2,
  "comfort": {"warmer": 0.002, "comfortable": 0.028, "cooler": 0.97},
  "neutral_temp": 25.1, "comfort_band": [24.6, 25.5], "setpoint": 25,
  "model": {"votes": 12, "personal": true, "shift_c": 1.66, "shift_sd_c": 0.55, "scale": 4.06,
            "prior": "ASHRAE Global Thermal Comfort Database II v2.1.0"},
  "auto": false
}
```

| `action` | `reason` |
|---|---|
| `none` | `NO_DATA`, `COMFORTABLE`, `SLIGHTLY_WARM`, `TOO_COOL_AC_OFF`, `SETPOINT_OK`, `ROOM_EMPTY`, `MODE_NOT_SUPPORTED` |
| `turn_on` | `TOO_WARM` |
| `set_temp` | `WARMER_SETPOINT`, `COOLER_SETPOINT` (one degree per step) |
| `turn_off` | `ROOM_EMPTY_LONG` (empty for 15 min) |

`SLIGHTLY_WARM`: the AC is off and the room is above the comfort band, but P(want cooler) is below the 60 % turn-on threshold. `target` holds a turn-on command the user may apply by hand; the automatic mode ignores it.

`auto: true` means the gateway applies the advice itself (`ADVISOR_AUTO=1`), always through the Safety Layer with source `ai`.

## Room state

```json
{
  "room": "room01",
  "node": {"status": "online", "since": 1794885609.9},
  "telemetry": {"ts": 1794885640.1, "temp": 28.4, "hum": 62.9, "presence": null,
                "simulated": false, "rssi": -55, "age_s": 3},
  "ac": {"power": "on", "mode": "cool", "temp": 25, "fan": "auto",
         "source": "app", "uncertain": false, "since": 1794885612.4},
  "safety": {"auto_hold_remaining_s": 1790, "auto_hold_source": "app", "compressor_ready_in_s": 0,
             "automation_enabled": true}
}
```

`ac` is the **expected** state (IR is one-way). `uncertain: true` means it may be out of date; `ac: null` means no command or remote press has been seen yet.
