# ADR 0001: Node Wi-Fi provisioning via the gateway

- Status: Accepted
- Date: 2026-11-03

## Context
Node Wi-Fi credentials were hard-coded in `config.h`. Changing the home router required re-flashing every node,
and a router failure stopped all node ⇄ gateway communication.

## Options considered
1. Gateway pushes home Wi-Fi credentials to nodes over MQTT; nodes fall back to a Pi-hosted AP.
2. Nodes always join a dedicated Pi-hosted network (needs a second Wi-Fi adapter or Ethernet on the Pi).
3. Nodes use ESP-NOW through an ESP32 bridge attached to the Pi.

## Decision
Option 1. No extra hardware, reuses the per-room MQTT ACL, and the same Pi AP serves as
router-failure fallback, demo network and first-time setup.

## Consequences
- Nodes need NVS-stored credentials, a test-before-switch step, and an AP fallback.
- Pi needs an AP watchdog that also switches back to home Wi-Fi.
- Credentials are sent without TLS on the LAN; MQTT over TLS is future work.
- Option 2 remains the product-grade path if a second Wi-Fi adapter is added.