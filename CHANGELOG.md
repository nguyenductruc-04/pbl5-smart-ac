# Changelog

Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning follows [SemVer](https://semver.org/).

## [Unreleased]
### Planned
- Milestone 2: Daikin IR decode + transmit (IRremoteESP8266)

## [Unreleased]
### Added
- ESP32-S3 Room Node firmware: Wi-Fi/MQTT with Last Will, SHT4x reading (simulated data fallback), plausibility filter, command handler (no IR yet).
- Raspberry Pi gateway: MQTT subscriber, telemetry validation, SQLite storage, command round-trip timing.
- Mosquitto config with per-room ACL (`%u` pattern) and password auth.
- Unit tests (pytest), lint (ruff), CI (GitHub Actions) including firmware compile check.
