# ADR 0006: Standalone network mode and QR device pairing

- Status: Accepted
- Date: 2026-11-21
- Extends: [ADR 0001](0001-node-wifi-provisioning.md)

## Context

Testing on real air conditioners happens away from the home router. Two things made each session slow:

1. **Network.** The Pi waited 120 s without home Wi-Fi before starting the backup AP, and returned to the home network every 5 minutes to retry. The node tried home Wi-Fi first on every boot (about 20 s including a scan), and while on the backup AP it left the AP every 5 minutes to retry home Wi-Fi, losing MQTT for about 30 s each time.
2. **Access.** Every new browser needed the 43-character `API_KEY`, read from `gateway/.env` over SSH, which meant carrying a laptop just to open the dashboard on a phone.

## Decision

### Network modes (Pi, chosen on the dashboard or `NETWORK_MODE` in `gateway/.env`, applied by `netwatch.py`)

| Mode | Behaviour |
|---|---|
| `auto` (default) | Unchanged from ADR 0001. |
| `standalone` | Start the backup AP immediately and never leave it. For field tests and demos with only the Pi and the node. |
| `home` | Never start the AP; leave it if it is up. |

Switching from the dashboard ("Mạng của Pi"): the API (running as the normal user) writes the choice to `gateway/network_mode`; `netwatch` (root) re-reads it every 15 s and writes its own state to `gateway/network_status.json`, which the dashboard shows ("Pi đang dùng Wi-Fi nhà…", "Đang chuyển…"). No service restart, no SSH. The `.env` value stays the default when no choice was made. Switching back to `auto` while on the AP retries home Wi-Fi immediately instead of after 5 minutes. Before a switch that will cut the page off, the dashboard says where to reconnect (`http://10.42.0.1:8000` on `SmartAC-Backup`, or `http://gateway.local:8000` at home).

The Pi has no RTC battery, and in `standalone` it has no Internet for NTP, so after a reboot its clock can be wrong. `/health` now returns the gateway time and the dashboard warns when it differs from the phone by more than 2 minutes, because telemetry and comfort votes would be stored with wrong timestamps.

### Node (firmware 0.9.0)

- Remembers in NVS whether the last successful connection was the backup AP and tries that network **first** on boot.
- While on the backup AP **and connected to the broker**, it never leaves. The Pi has one Wi-Fi radio, so while it serves the AP the broker is not on the home network; when the Pi goes home it stops the AP, the node loses Wi-Fi and reconnects through the normal path (last network first, then the other).
- If the broker has been unreachable on the backup AP for 5 minutes, it scans first and only tries home Wi-Fi when that SSID is actually visible. The scan does not drop the current connection.

No mode switch is needed on the node: it follows whatever network the Pi provides.

### Device pairing by QR code

- A signed-in dashboard can create a pairing code (`POST /pairing`): random (96 bits), single use, valid 5 minutes, kept only in RAM.
- The QR code encodes `http://<pi>:8000/#pair=<code>`. The code sits after `#`, so browsers never send it to the server or write it to logs. When the page was opened as `gateway.local`, the URL uses the Pi's IP on the same interface instead, because `.local` names often do not resolve on Android.
- The new device exchanges the code for the app key (`POST /pairing/claim`, no key needed) and stores it like a typed key. Failed claims are limited to 10 per minute.

Considered and postponed: user accounts with roles (owner / member / guest). They are the right long-term answer and would let comfort votes belong to a person, but need password storage, sessions and a first-run setup (planned as a later release). Pairing removes most of the day-to-day friction now and keeps the security model unchanged (one app key per installation).

## Consequences

- A field session is: power the Pi and the node, join `SmartAC-Backup` on the phone, scan a QR code. No laptop.
- Anyone who scans a valid code gets the full app key. The dashboard says so next to the code, the code expires in 5 minutes, and it works once.
- `standalone` must be switched back to `auto` at home, or the Pi never rejoins the home network. The dashboard makes this one tap, but it is still a step to remember.
- Anyone with the app key can move the Pi off the home network. Same trust level as controlling the AC.
- The node now writes NVS only when the network type changes, not on every connection.
- New gateway dependency: `segno` (pure Python QR encoder, no system libraries).
