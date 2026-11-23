# ADR 0009: Detect and switch the AC's IR protocol at run time

- Status: Accepted
- Date: 2026-11-24

## Context

Until v0.10.0 the protocol the node sends (`IR_PROTOCOL`, `IR_MODEL`) was compiled into the firmware, and the gateway used `IR_PROTOCOL` from `.env` to decide which overheard remote frames may update the expected AC state. Moving the node to another room or another brand of AC meant editing `config.h`, reflashing over USB and editing `.env` on the Pi. The first field test on a Casper unit also showed that guessing the protocol is hard: the remote decoded as `ELECTRA_AC` with implausible temperatures (ir-circuit.md, open items).

Commercial universal controllers (Sensibo, Broadlink, Tado) let the user point the original remote at the device and press a button; the device recognises the protocol, sends a test command, and asks whether the AC reacted.

## Decision

- **Protocol lives on the node, in NVS.** `config.h` only provides the first-boot default. The node reports `ir_protocol` / `ir_model` in every telemetry message, so the gateway always knows what the node will send, also after a reflash.
- **Switching is a request the node can refuse.** The gateway sends `{"cfg_id", "ir": {...}}` on the existing `config` topic; the node checks the name with `IRac::isProtocolSupported()` of the installed IRremoteESP8266 (2.9.0) and answers on `config_result`. The API waits for that answer (same timeout as commands), so the user sees "not supported" or "node did not answer" immediately instead of a silent failure.
- **Learn mode reports everything for a bounded time** (default 60 s, at most 300 s): AC frames as today, plus frames that are not an AC state (`"ac": false`, protocol name, bit count). Outside learn mode non-AC frames stay ignored, so TV remotes do not create noise.
- **Detection proposes, the user decides.** The UI shows each detected protocol with the state it decoded ("bật, mát, 25 °C"). If that matches the remote's screen, the decoding is right; if not (the Casper case), the protocol name is suspect even though the library accepted the frame. After switching, "Bật thử / Tắt thử" sends a real command and the admin confirms whether the AC beeped. The confirmation is stored with who and when, and cleared whenever the protocol changes.
- **Brand hints are only hints.** A small table maps common brands sold in Vietnam to IRremoteESP8266 protocols to try in order. Rebadged brands (Casper, Nagakawa, Funiki…) are not listed: their protocol depends on the OEM, so detection is the way.
- **Per-room expected protocol.** Overheard frames update the expected state only if their protocol equals the room's current protocol; `IR_PROTOCOL` in `.env` remains a fallback for nodes on older firmware. A switch marks the AC state uncertain. A telemetry report of the old protocol within 15 s after a switch is ignored (it was sent before the switch).
- Only admins can learn, switch or confirm: a wrong protocol makes the AC uncontrollable for everyone.

## Consequences

- Moving a node to another AC needs no laptop: detect, test, confirm in the dashboard or app.
- The node remembers the protocol across power cuts; holding BOOT at start-up still only clears Wi-Fi.
- A protocol the library decodes wrongly (Casper) is still a problem; the decoded-state check makes it visible instead of hiding it. Raw learning (record and replay each button, as `firmware/tools/ir_replay` does) is the fallback for such units and is not part of this ADR.
- Older nodes keep working; switching shows "node did not answer" until they are reflashed with 0.11.0.

## Alternatives considered

- **Automatic trial of every protocol until the AC beeps.** Needs a microphone or a person listening anyway, and sends dozens of frames, some of which may change modes unexpectedly.
- **Keep the protocol in the gateway only and send it with every command.** Works, but the node could no longer act offline (overheard remote while the broker is down) and two sources of truth could disagree.
