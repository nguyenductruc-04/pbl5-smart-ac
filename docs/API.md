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
| DELETE | `/rooms/{room}/auto-hold` | Let automation resume now (app key only). |
| GET | `/rooms/{room}/telemetry?limit=&since=&until=` | Telemetry history, newest first. |
| GET | `/rooms/{room}/telemetry/series?hours=&points=` | Bucket-averaged temperature/humidity for charts, oldest first. |
| GET | `/rooms/{room}/commands?limit=` | Commands sent and their results. |
| GET | `/rooms/{room}/decisions?limit=` | Safety Layer audit log. |
| POST | `/rooms/{room}/comfort` | Record a comfort vote (app key only). |
| GET | `/rooms/{room}/comfort?limit=&since=` | Comfort votes with their context, newest first (labelled data for Milestone 6). |
| DELETE | `/rooms/{room}/comfort/{id}` | Undo a vote within 120 s (app key only). |
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

## Errors

```json
{"error": {"code": "COMPRESSOR_MIN_OFF", "message": "...", "retry_after_s": 150}}
```

When `retry_after_s` is present the response also carries a `Retry-After` header.

| HTTP | `code` | Meaning |
|---|---|---|
| 401 | `UNAUTHORIZED` | Missing or wrong key |
| 403 | `SOURCE_NOT_ALLOWED`, `FORBIDDEN` | Key not allowed to do this |
| 404 | `ROOM_NOT_FOUND` | No node has ever reported for this room |
| 409 | `COMPRESSOR_MIN_OFF`, `COMPRESSOR_MIN_ON`, `MANUAL_HOLD`, `STATE_UNCERTAIN`, `TELEMETRY_STALE`, `ROOM_EMPTY`, `STEP_TOO_LARGE` | Rejected by the Safety Layer |
| 422 | `TEMP_OUT_OF_RANGE`, or FastAPI validation detail | Invalid request |
| 429 | `RATE_LIMIT` | Too frequent |
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
