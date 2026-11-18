# Changelog

Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning follows [SemVer](https://semver.org/).

## [Unreleased]

## [0.6.0] - 2026-11-XX
### Added
- Safety Layer (`gateway/safety.py`): a pure, unit-tested gate that every command passes. Compressor minimum off-time, rate limits, temperature windows, and stricter rules for automatic sources (auto-hold after human action, fresh telemetry, 1 °C steps, no power-on when the room is empty).
- Expected AC state tracking in SQLite (`ac_state`), updated from command results and overheard remote presses, flagged *uncertain* after any gap; survives restarts.
- Audit log of every Safety Layer decision (`decisions` table).
- REST API (`gateway/api.py`, FastAPI) under `/api/v1`: room state, history, commands, auto-hold. The command source is derived from the API key (app vs automation).
- Defined offline behaviour: no command queuing, `503`/`504` errors with reason codes, clock-rollback healing at start-up.
- ADR 0002, `docs/API.md`, setup step 8.

### Changed
- The gateway service now runs `api.py` (MQTT ingest and API in one process). `gateway.py` alone still works for ingest only.
- SQLite opened in WAL mode; `*.db-wal` and `*.db-shm` are git-ignored.
- CI installs `gateway/requirements-dev.txt`.

## [0.5.0] - 2026-11-17
### Added
- Real climate sensing with Sensirion SHT3x (SHT30/31/35) over I²C; SHT4x still supported (`CLIMATE_SENSOR` in `config.h`).
- Presence sensing with HLK-LD2420 (24 GHz radar) via its digital output; telemetry is sent immediately when presence changes.
- Sensor liveness: presence is reported as `null` (unknown), not `false`, when the LD2420 loses power or a wire; a failed SHT3x is re-initialised every 30 s.
- `firmware/tools/sensor_check`: I²C scan, LD2420 pin and firmware-variant detection, live sensor monitor.
- `docs/hardware/sensors.md`, setup step 7. `show_data.py` shows presence and how many days of real data have been collected.

### Changed
- Simulated climate data is off by default (`CLIMATE_SIM_FALLBACK 0`) so it cannot contaminate the training data.
- CI compiles `sensor_check` and installs the Adafruit SHT31 library.

## [0.4.0] - 2026-11-17
### Added
- Pi Wi-Fi watchdog (`gateway/netwatch.py`, service `pbl5-netwatch`): starts the backup access point `SmartAC-Backup` (10.42.0.1) after 120 s without home Wi-Fi and retries home Wi-Fi every 5 min.
- Room node stores home Wi-Fi in NVS, moves to the backup AP when home Wi-Fi or the broker has been unreachable for 120 s, and tries to return home every 5 min.
- Wi-Fi provisioning over MQTT (`gateway/push_wifi.py`, topics `config` / `config_result`): the node tests new credentials before saving them; the password is never echoed back; the retained message is cleared once a result arrives.
- BOOT-button reset of the stored Wi-Fi.
- ADR 0001 (node Wi-Fi provisioning).

### Fixed (found during hardware testing)
- Watchdog: home Wi-Fi did not come back after the AP was stopped; saved connections are now activated explicitly.
- Node stayed on home Wi-Fi when the router was up but the Pi was gone; it now follows the broker.
- Backup AP came up as WPA1 and ESP32 core 2.0.x refused it (reason 201); the AP is now WPA2/CCMP only.
- First connection after boot could fail with auto-reconnect disabled; up to two early retries.
- BOOT reset erased the last applied config id, so a stale retained config was applied again.

### Known limitations
- Wi-Fi credentials travel unencrypted over MQTT inside the local network (MQTT over TLS is a future step).
- 2.4 GHz networks only.

## [0.3.0] - 2026-11-14
### Added
- Room node sends real IR on MQTT commands via IRremoteESP8266 `IRac`; A/C protocol selectable in `config.h` (`IR_PROTOCOL`, default `DAIKIN`).
- Node-side command validation (power/mode/fan values, 16–30 °C); invalid commands rejected with an error code.
- Remote eavesdropping: decoded A/C remote frames published to `home/<room>/ir_event`; gateway stores them in `ir_events`.
- Self-interference handling: receiver disabled while sending + 300 ms blanking window.
- IR loopback test tool (`firmware/tools/ir_loopback`) and IR hardware documentation (`docs/hardware/ir-circuit.md`).

### Changed
- ESP32 Arduino core pinned to 2.0.17 (IRremoteESP8266 incompatible with core 3.x).
- CLI temperature limit aligned with the node (16–30 °C).
- Command round trip now includes IR airtime: median 468 ms, p95 481 ms (N = 20).

### Known limitations
- Not yet tested on a real Daikin unit or remote; IR LED driven at ~40 mA from 3V3, range unverified.
## [0.2.0] - 2026-11-04
### Added
- Room node discovers the gateway via mDNS (`gateway.local`) on every MQTT (re)connect, with a fallback address; node advertises itself as `<room>.local`.
- ADR 0001: node Wi-Fi provisioning via the gateway.

### Changed
- `config.h`: `MQTT_HOST` replaced by `MQTT_HOSTNAME` + `MQTT_HOST_FALLBACK`.

## [0.1.1] - 2026-11-03
### Changed
- Room node disables Wi-Fi modem sleep (`WiFi.setSleep(false)`): command round-trip max latency 1909 ms → 54 ms (median 28 ms, p95 38 ms, N = 20). Trade-off: higher idle power on mains-powered nodes.

## [0.1.0] - 2026-11-02
### Added
- Validated end-to-end on hardware: ESP32-S3 ⇄ Wi-Fi/MQTT ⇄ Raspberry Pi 5 (mean 427 ms, min 35 ms, max 1909 ms command round trip, N = 21).
- ESP32-S3 Room Node firmware: Wi-Fi/MQTT with Last Will, SHT4x reading (simulated data fallback), plausibility filter, command handler (no IR yet).
- Raspberry Pi gateway: MQTT subscriber, telemetry validation, SQLite storage, command round-trip timing.
- Mosquitto config with per-room ACL (`%u` pattern) and password auth.
- Unit tests (pytest), lint (ruff), CI (GitHub Actions) including firmware compile check.

[Unreleased]: https://github.com/nguyenductruc-04/pbl5-smart-ac/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/nguyenductruc-04/pbl5-smart-ac/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/nguyenductruc-04/pbl5-smart-ac/compare/v0.1.1...v0.2.0
[0.1.1]: https://github.com/nguyenductruc-04/pbl5-smart-ac/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/nguyenductruc-04/pbl5-smart-ac/releases/tag/v0.1.0