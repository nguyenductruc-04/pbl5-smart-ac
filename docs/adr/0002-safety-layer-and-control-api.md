# ADR 0002: Safety Layer, control priority, offline behaviour and REST API

- Status: Accepted; amended by [ADR 0005](0005-missed-ir-commands.md) (manual early start can be confirmed)
- Date: 2026-11-17

## Context

Until v0.4.0 the only way to send a command was `send_command.py`, which publishes straight to MQTT. The dashboard (M5) and the AI suggestion service (M6) need a programmatic entry point, and three properties of the system make an unguarded entry point unsafe:

1. **IR is one-way.** The air conditioner never confirms anything. The gateway only holds an *expected* state, which becomes wrong whenever a frame is missed or the remote is used while nobody is listening.
2. **Several sources will issue commands** (person with the remote, person with the app, schedule rules, an ML model). A model that oscillates, or a retry loop in a client, can toggle the compressor repeatedly.
3. **Any link can fail**: node Wi-Fi, the broker, the gateway process, the Pi's clock (no RTC battery, and no NTP while on the backup AP from ADR 0001).

Short-cycling a compressor (restarting it before refrigerant pressures have equalised) increases start-up load and wear; an anti-short-cycle delay of about 3 minutes is standard practice in HVAC controls ([US 4991049](https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/4991049), [US 5960639](https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/5960639)). Modern split units normally enforce their own delay, so our rule is defence in depth, not the only protection. We have not verified the built-in delay on the target Daikin unit.

## Decision

### 1. One gate: every command passes `safety.evaluate()`

`safety.evaluate(source, target, room_view, now, policy) -> Decision` is a **pure function**: no clock, no MQTT, no database. Everything it needs is passed in. Each rule is unit-tested in isolation, and every decision carries a machine-readable reason code that is logged (`decisions` table) and returned by the API.

`control.CommandService` is the only code path from the API to MQTT: resolve the request into a full target state, evaluate, log, publish, wait for `command_result` with a deadline. Commands for one room are serialised with a per-room lock so concurrent requests cannot slip past rate limits.

### 2. Two classes of source; the last human wins

| Class | Sources | Treatment |
|---|---|---|
| Manual | `remote` (overheard), `app`, `cli` | Light rules. A manual action starts an **auto-hold** (remote 60 min, app 30 min). |
| Automatic | `rule`, `ai` | Blocked during auto-hold and subject to all rules below. |

The remote does not outrank the app: both are a person expressing intent, so the most recent one applies. The user can end the hold early (`DELETE /rooms/{room}/auto-hold`).

The **API key determines the source**, not the request body: the app key can only produce `app` commands, the automation key only `rule`/`ai`. A buggy or compromised automation client cannot claim to be a person.

### 3. Rules

| Code | Applies to | Rule (defaults, see `safety.Policy`) |
|---|---|---|
| `NODE_OFFLINE` | all | Node must be online. Commands are never queued. |
| `COMPRESSOR_MIN_OFF` | all | After power-off, wait 180 s before power-on (not for `fan` mode). Since v0.10.0 a person may confirm an early start (ADR 0005). |
| `TEMP_OUT_OF_RANGE` | manual / auto | Manual 16–30 °C; automatic 24–29 °C. |
| `RATE_LIMIT` | manual / auto | Manual ≥ 2 s between commands; automatic ≥ 600 s. |
| `STATE_UNCERTAIN` | auto | No automatic control while the expected state may be wrong. |
| `MANUAL_HOLD` | auto | Blocked while an auto-hold is active. |
| `TELEMETRY_STALE` | auto | Latest telemetry must be ≤ 120 s old. |
| `ROOM_EMPTY` | auto | Never turn on when presence is known to be false. |
| `STEP_TOO_LARGE` | auto | At most 1 °C change per command. |
| `COMPRESSOR_MIN_ON` | auto | After power-on, run 300 s before an automatic power-off. |
| `NO_CHANGE` | auto | Target equals expected state: skipped, nothing sent. |

Two deliberate asymmetries:

- **A person can always turn the unit off.** Manual power-off is exempt from rate limiting and from `COMPRESSOR_MIN_ON`.
- **A person may resend the current state** (the AC may have missed a frame); automation may not.

### 4. Expected state has a single writer and survives restarts

The gateway MQTT handler is the only writer of `ac_state`. It updates the state when a node reports `ok` for a command, or when the node overhears the remote (`ir_event`). On/off transition times and the hold deadline are stored in SQLite, so a gateway restart does not reset the compressor timer.

The state is flagged **uncertain** when the gateway may have missed something: the node went offline, a command timed out (the IR frame may or may not have been sent), a malformed remote event arrived, or the gateway itself restarted. Uncertainty blocks automatic sources only; any manual command or overheard remote press clears it.

### 5. Behaviour when a link is down

| Failure | Behaviour |
|---|---|
| Node offline (Last Will) | `503 NODE_OFFLINE` immediately. Nothing is queued: a "power on" delivered an hour late is worse than an error. State becomes uncertain. |
| Gateway lost the broker | `503 BROKER_UNAVAILABLE`. The gateway does not call `publish()` while disconnected, because the MQTT client would buffer the QoS 1 message and deliver it after reconnecting. |
| Node silent | `504 NODE_TIMEOUT` after 5 s; state becomes uncertain. A late result still synchronises the state. |
| Node cannot send | `502 NODE_ERROR`; state unchanged. |
| Gateway / Pi down | The AC keeps its last state and the physical remote keeps working. The node does nothing on its own. |
| Pi clock moved backwards | At start-up, timestamps in the future are pulled back to "now", so waits are bounded by the policy values instead of lasting hours. At runtime a future timestamp counts as "just happened" (fail-safe). |

### 6. REST API in the gateway process

FastAPI, versioned under `/api/v1`, served by the same process that ingests MQTT (`python api.py`). One process means one MQTT client and no race between "result received" and "state updated". `POST /commands` is synchronous: it returns after the node answered or the deadline passed, which matches the measured round trip (median 468 ms with real IR, v0.3.0). Reference: [docs/API.md](../API.md).

## Alternatives considered

- **Rules in firmware.** Rejected as the main location: harder to test and change, and the node has no wall clock. The node keeps its own input validation (16–30 °C, known modes).
- **Separate API and ingest processes.** More isolation, but needs cross-process signalling for command results and a second MQTT identity. Not justified for one Pi.
- **Queue commands for offline nodes.** Rejected: stale commands are unsafe and surprising.
- **Asynchronous command API (202 + polling).** Unnecessary at ~0.5 s latency; revisit with WebSocket updates in M5.
- **Remote outranks app.** Rejected: both are human intent.

## Consequences and known limitations

- After a node outage or gateway restart, automation stays blocked until a person acts once. This is conservative. The proper fix is for the node to report its own AC state on reconnect (follow-up issue).
- The expected state is still unconfirmed. A frame the AC missed leaves the gateway wrong until the next manual action.
- `send_command.py` bypasses the Safety Layer; it remains a debugging tool only.
- The API uses plain HTTP with static keys, intended for the LAN/backup AP or over Tailscale. It must not be exposed to the Internet.
- Policy values are engineering defaults, not measurements from the target unit.
