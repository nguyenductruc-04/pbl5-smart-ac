# Gateway REST API (v1)

Base URL: `http://gateway.local:8000/api/v1` (or `http://10.42.0.1:8000/api/v1` on the backup AP).
Interactive documentation generated from the code: `http://gateway.local:8000/docs`.

The dashboard at `http://gateway.local:8000/` is a client of this API ([ADR 0003](adr/0003-dashboard.md)).

Design rationale: [ADR 0002](adr/0002-safety-layer-and-control-api.md).

## Authentication (v0.10.0, [ADR 0007](adr/0007-user-accounts.md))

People sign in with an account; every endpoint except `/health`, `/setup/status`, `/setup`, `/auth/register`, `/auth/login` and `/pairing/claim` needs one of:

| Header | Who | Role |
|---|---|---|
| `Authorization: Bearer <token>` | a person, token from `/setup`, `/auth/login` or `/pairing/claim` | `admin`, `member` or `guest` |
| `X-API-Key: $API_KEY` | scripts and `curl` on the Pi | same rights as `admin`, commands as source `app` |
| `X-API-Key: $API_KEY_AUTOMATION` (optional) | automation | commands with `source` `rule` or `ai` only |

| Role | Can |
|---|---|
| `admin` | everything: control, votes, pairing, network mode, accounts |
| `member` | control the AC, resend/sync, comfort votes, pairing its own devices |
| `guest` | read only |
| `pending` | nothing: a self-registered account waiting for an admin |

Plain HTTP: use on the local network or over Tailscale only.

### First setup, accounts and sessions

```bash
curl http://gateway.local:8000/api/v1/setup/status
# {"claimed": false, "device_id": "a1b2c3d4", "version": "0.10.0"}

curl -X POST http://gateway.local:8000/api/v1/setup -H "Content-Type: application/json" \
  -d '{"code": "XXXX-XXXX-XXXX", "username": "truc", "password": "...", "device": "laptop"}'
# 201 {"token": "...", "user": {"username": "truc", "role": "admin", ...}}
```

The setup code is printed on the label on the Pi (`gateway/setup_code`, made by `setup_label.py`). `/setup` works only while the Pi has no admin; holding the reset button for 10 s removes all accounts and opens it again. Others call `/auth/register` (account starts as `pending`) and an admin grants a role with `PUT /users/{username}`.

Tokens are random 256-bit values; the Pi stores only their SHA-256. A session expires after 90 days without use. Changing the password signs out every other device; deleting an account or changing its role takes effect on the next request.

| Method | Path | Who | Purpose |
|---|---|---|---|
| GET | `/setup/status` | anyone | `claimed`, `device_id`, `version` |
| POST | `/setup` | anyone with the setup code | First admin; `code`, `username`, `password`, optional `display_name`, `device` |
| POST | `/auth/register` | anyone | New account, `pending` until approved |
| POST | `/auth/login` | anyone | `{"token", "user"}`; `device` names the session |
| POST | `/auth/logout` | signed in | Ends this session (`204`) |
| GET | `/auth/me` | signed in | Own account, role and sessions (`kind: "key"` for API keys) |
| PUT | `/auth/password` | signed in | `old_password`, `new_password` |
| GET | `/users` | admin | All accounts, pending first |
| PUT | `/users/{username}` | admin | `{"role": ...}` with `admin`, `member` or `guest`: approve or change |
| DELETE | `/users/{username}` | admin | Remove the account and its sessions |

Usernames: 3–32 characters, lowercase letters, digits, `.`, `_`, `-`, case-insensitive. Passwords: 8–128 characters, not equal to the username; hashed with scrypt.

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Liveness. `503` when the gateway lost the MQTT broker. No key. |
| GET | `/policy` | Safety Layer thresholds in effect. |
| GET | `/rooms` | Known rooms and node status. |
| GET | `/rooms/{room}` | Node status, latest telemetry, expected AC state, safety timers. |
| POST | `/rooms/{room}/commands` | Send a command through the Safety Layer. |
| POST | `/rooms/{room}/commands/resend` | Send the expected state again, when the AC seems to have missed a frame (member or admin). |
| PUT | `/rooms/{room}/ac-state` | Tell the gateway what the AC is really doing; nothing is sent (member or admin). |
| POST | `/pairing` | Create a one-time code and QR image to sign in another device (member or admin). |
| GET | `/system/network` | Pi network mode and Wi-Fi state reported by `netwatch`. |
| PUT | `/system/network` | Change the network mode: `auto`, `standalone` or `home` (admin). |
| POST | `/pairing/claim` | Exchange a pairing code for a session of the person who made it. No login needed. |
| DELETE | `/rooms/{room}/auto-hold` | Let automation resume now (member or admin). |
| GET | `/rooms/{room}/telemetry?limit=&since=&until=` | Telemetry history, newest first. |
| GET | `/rooms/{room}/telemetry/series?hours=&points=` | Bucket-averaged temperature/humidity for charts, oldest first. |
| GET | `/rooms/{room}/commands?limit=` | Commands sent and their results. |
| GET | `/rooms/{room}/decisions?limit=` | Safety Layer audit log. |
| POST | `/rooms/{room}/comfort` | Record a comfort vote (member or admin). |
| GET | `/rooms/{room}/comfort?limit=&since=` | Comfort votes with their context, newest first (labelled data for Milestone 6). |
| DELETE | `/rooms/{room}/comfort/{id}` | Undo your own vote within 120 s (admins: any vote). |
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

### When the AC missed a command (v0.10.0, [ADR 0005](adr/0005-missed-ir-commands.md))

- **Early start.** A manual power-on during the compressor rest period returns `409 COMPRESSOR_MIN_OFF` with `"can_confirm": true`. Sending the same command with `"confirm": true` is accepted (`code: EARLY_START_CONFIRMED`). Automatic commands cannot be confirmed.
- **Resend.** `POST /rooms/{room}/commands/resend` (no body) sends the expected state again; response as above with `code: RESEND`. `409 NO_STATE` if the state was never known.
- **Sync.** `PUT /rooms/{room}/ac-state` with any of `power`, `mode`, `temp`, `fan` sets the expected state without sending IR, clears `uncertain`, starts the app auto-hold and leaves the compressor timers alone. Returns the room state; the decision log gets an entry with verdict `sync`.

## Device pairing (v0.10.0, [ADR 0006](adr/0006-field-network-and-device-pairing.md))

```bash
curl -X POST -H "X-API-Key: $API_KEY" http://gateway.local:8000/api/v1/pairing
```

```json
{"code": "pfpAF2zAXt4k7aPh", "url": "http://10.42.0.1:8000/#pair=pfpAF2zAXt4k7aPh",
 "expires_in_s": 300, "qr": "data:image/svg+xml;charset=utf-8,..."}
```

## Network mode (v0.10.0)

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

`?ttl_s=` sets the lifetime (60–900 s, default 300). The dashboard uses 900 s for the link it shows after a network switch: browsers keep the session per address, so `http://10.42.0.1:8000` is a new page that would otherwise ask to sign in again.

Opening `url` on another device signs it in as the person who created the code: the dashboard posts the code to `/pairing/claim`, which returns `{"token": "..."}` once (a code created with the `API_KEY` returns `{"api_key": "..."}` instead). A used, unknown or expired code gives `410 PAIR_INVALID`; more than 10 failures per minute give `429 PAIR_TOO_MANY`. Codes live in RAM only and vanish when the gateway restarts.

## Errors

```json
{"error": {"code": "COMPRESSOR_MIN_OFF", "message": "...", "retry_after_s": 150}}
```

When `retry_after_s` is present the response also carries a `Retry-After` header.

| HTTP | `code` | Meaning |
|---|---|---|
| 401 | `UNAUTHORIZED`, `SESSION_INVALID` | Not signed in, wrong key, or session expired / signed out |
| 401 | `LOGIN_FAILED` | Wrong username or password |
| 403 | `SOURCE_NOT_ALLOWED`, `FORBIDDEN`, `CONFIRM_NOT_ALLOWED`, `NOT_YOUR_VOTE` | Role or key not allowed to do this |
| 403 | `ACCOUNT_PENDING` | Account waiting for an admin |
| 403 | `SETUP_CODE_INVALID`, `WRONG_PASSWORD` | Wrong setup code / current password |
| 409 | `ALREADY_CLAIMED`, `NOT_CLAIMED`, `USERNAME_TAKEN`, `LAST_ADMIN` | Setup already done / not done yet, name in use, would leave no admin |
| 404 | `USER_NOT_FOUND` | No such account |
| 422 | `BAD_USERNAME`, `BAD_PASSWORD` | Rules above |
| 404 | `ROOM_NOT_FOUND` | No node has ever reported for this room |
| 409 | `COMPRESSOR_MIN_OFF`, `COMPRESSOR_MIN_ON`, `MANUAL_HOLD`, `STATE_UNCERTAIN`, `TELEMETRY_STALE`, `ROOM_EMPTY`, `STEP_TOO_LARGE` | Rejected by the Safety Layer (`COMPRESSOR_MIN_OFF` on a manual command adds `can_confirm: true`) |
| 409 | `NO_STATE` | Nothing to resend yet |
| 410 | `PAIR_INVALID` | Pairing code used, unknown or expired |
| 422 | `TEMP_OUT_OF_RANGE`, or FastAPI validation detail | Invalid request |
| 429 | `RATE_LIMIT`, `PAIR_TOO_MANY`, `LOGIN_LOCKED`, `SETUP_TOO_MANY`, `REGISTER_TOO_MANY`, `TOO_MANY_PENDING` | Too frequent: 5 wrong passwords per name in 5 min, 5 wrong setup codes per minute, 10 registrations per minute, at most 20 pending accounts |
| 502 | `NODE_ERROR` | Node answered but could not send the IR frame |
| 503 | `NODE_OFFLINE`, `BROKER_UNAVAILABLE` | A link is down; the command was **not** queued |
| 504 | `NODE_TIMEOUT` | No answer within 5 s; the AC state is now marked uncertain |

## Comfort votes

The dashboard asks "Bạn thấy thế nào?" and records the answer together with the latest sensor readings and the expected AC state, so each vote is a self-contained training sample.

```bash
curl -X POST http://gateway.local:8000/api/v1/rooms/room01/comfort \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"vote": "cooler"}'
```

`vote` is `cooler` (wants it cooler), `comfortable` or `warmer`; stored as −1 / 0 / +1. Response `201`:

```json
{"id": 12, "ts": 1794983381.1, "vote": "cooler", "temp": 29.4, "hum": 73.2, "presence": true,
 "telemetry_age_s": 6.2, "ac_power": "on", "ac_mode": "cool", "ac_temp": 26, "ac_uncertain": false,
 "user_id": 2, "username": "lan"}
```

`user_id` and `username` record who voted (`null` for votes made before v0.10.0 or with the `API_KEY`), so the comfort model can later be personalised per person rather than per room.

| HTTP | `code` | Meaning |
|---|---|---|
| 403 | `FORBIDDEN` | Guests and the automation key: only members and admins vote |
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
