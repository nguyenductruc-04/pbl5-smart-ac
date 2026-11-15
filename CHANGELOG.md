# Changelog

Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning follows [SemVer](https://semver.org/).

## [Unreleased]
### Planned
- Milestone 2: Daikin IR decode + transmit (IRremoteESP8266)
### Added
- Gateway Wi-Fi watchdog (`gateway/netwatch.py`, systemd `pbl5-netwatch`): starts backup AP `SmartAC-Backup` (10.42.0.1)
  after 2 min without home Wi-Fi, retries home networks every 5 min.

### Fixed
- Watchdog activates saved home connections explicitly; NetworkManager may block autoconnect after a user
  disconnect or repeated failures, which would leave the Pi stuck in AP mode.

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