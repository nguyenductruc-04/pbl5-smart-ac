# ADR 0007: User accounts, first setup by QR code and a reset button

- Status: Accepted
- Date: 2026-11-22
- Supersedes: the access part of [ADR 0006](0006-field-network-and-device-pairing.md) (pairing now signs in as a person)

## Context

Until v0.9.0 the API had one shared secret, `API_KEY`. Testing on phones showed the problems of that design:

- The key had to be read from `gateway/.env` over SSH and typed or paired into every browser, and browsers keep it per address (`gateway.local`, the home IP and `10.42.0.1` are three different pages).
- Everyone with the key had full rights, including changing the network mode; there was no way to let a roommate watch the room without letting them control it, or to revoke one phone.
- Comfort votes could not say who voted, although comfort is personal (ADR 0004).
- A native Android app (planned for v0.10.0) needs a normal sign-in, not a shared secret.

Consumer smart-home devices solve this the same way: the owner claims the device with a code printed on it, other people get access from the owner, and a physical button returns the device to factory state.

## Decision

### Roles

| Role | Rights |
|---|---|
| `admin` | everything, including network mode and accounts |
| `member` | control the AC, resend / sync, comfort votes, pair own devices |
| `guest` | read only |
| `pending` | none: self-registered, waiting for an admin |

There is always at least one admin (`LAST_ADMIN`). The `API_KEY` keeps working with admin rights for `curl` and scripts on the Pi; `API_KEY_AUTOMATION` is unchanged.

### First setup

On first start the gateway creates `gateway/setup_code` (12 characters from an alphabet without 0/O/1/I/L, about 59 bits, file mode 600) and `gateway/device_id`. `setup_label.py` prints a label with:

- the code as text, and a QR code `pbl5://setup?id=<device_id>&code=<code>` for the Android app;
- the backup Wi-Fi name and password, and a standard `WIFI:` QR code so a phone camera can join it.

While no admin exists, `POST /setup` with the code creates the first admin and returns a session. Five wrong codes per minute lock the endpoint for a minute. After that, `/setup` answers `409 ALREADY_CLAIMED`.

Threat model: someone needs both the label and access to the Pi's network, and only in the window before the owner claims the Pi or after a reset. Like a printed Wi-Fi password, the label is the secret; it is stuck on the inside or bottom of the case.

### Other people

They register themselves (`POST /auth/register`); the account is `pending` and cannot sign in. An admin sees "Có N tài khoản đang chờ bạn duyệt" on the dashboard and grants `member` or `guest`, or refuses (deletes). This avoids typing other people's passwords on the admin's phone. Registration is rate limited (10 per minute, at most 20 pending) because the backup Wi-Fi is reachable by anyone nearby who knows its password.

### Passwords and sessions

- scrypt (N = 2^14, r = 8, p = 1, 16-byte salt) from the Python standard library: no new dependency, about 50 ms on the Pi 5. A dummy hash is checked for unknown usernames so timing does not reveal which names exist.
- Session token: 32 random bytes; the database stores only its SHA-256, so a copy of `pbl5.db` does not let anyone sign in. Sliding expiry: 90 days without use.
- Five wrong passwords for one name in 5 minutes lock that name for the rest of the window.
- Role changes and deletions apply on the next request (the role is read from `users` on every request, not stored in the token).
- Changing the password signs out every other session.

### Pairing

`POST /pairing` (QR in "Thêm thiết bị") is kept, but the code now signs the other device in **as the person who created it**, with a new session. A code created with the `API_KEY` still returns the key.

### Reset button

A push button between GPIO 17 (pin 11) and GND (pin 9), read by `reset_button.py` (`pbl5-reset.service`, system Python with `gpiozero`). Holding it for 10 s:

- deletes all accounts and sessions;
- forgets the network mode chosen on the dashboard (back to `NETWORK_MODE` from `.env`), so a Pi stuck on "home only" with a changed router becomes reachable again on the backup Wi-Fi;
- keeps telemetry, commands, decisions and comfort votes, and keeps the setup code, so the same label works for the new owner.

A 10 s hold avoids accidental resets; a short press only logs.

### Discovery

`pbl5.avahi.service` advertises `_pbl5._tcp` on port 8000 so the Android app finds the Pi on the LAN without an IP address; on the backup Wi-Fi the app uses the fixed `10.42.0.1`.

## Consequences

- The dashboard asks for a username and password instead of a key; "Thêm thiết bị" still avoids typing on a second phone.
- Votes carry `user_id` / `username`; older votes have `NULL` and stay usable for the room-level model.
- Accounts live in the same SQLite file (`users`, `sessions`); `store.init` adds the vote columns to existing databases.
- Someone on the network can lock a name for 5 minutes by guessing wrong on purpose. Acceptable in a home; the `API_KEY` on the Pi still works meanwhile.
- Physical access to the Pi still means full control (reset button, SD card), as with any home device.
- Plain HTTP remains: tokens can be sniffed on an open network. The backup Wi-Fi is WPA2 and the home network is trusted; HTTPS with a local CA is out of scope for the course project.

## Alternatives considered

- **Keep the shared key, improve pairing.** Does not give roles, revocation or per-person votes.
- **Admin creates accounts with a password.** The admin would know other people's passwords. Self-registration plus approval is what products such as shared smart-home apps do.
- **JWT.** Stateless tokens cannot be revoked one by one without a deny list; a session table on the same SQLite database is simpler and revocable.
- **bcrypt / argon2.** Need a compiled dependency; scrypt from `hashlib` is a memory-hard KDF accepted by OWASP.
