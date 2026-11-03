# Changelog

Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning follows [SemVer](https://semver.org/).

## [Unreleased]
### Planned
- Milestone 2: Daikin IR decode + transmit (IRremoteESP8266)

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

[Unreleased]: https://github.com/nguyenductruc-04/pbl5-smart-ac/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/nguyenductruc-04/pbl5-smart-ac/compare/v0.1.1...v0.2.0
[0.1.1]: https://github.com/nguyenductruc-04/pbl5-smart-ac/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/nguyenductruc-04/pbl5-smart-ac/releases/tag/v0.1.0