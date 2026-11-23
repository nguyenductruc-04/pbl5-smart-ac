# ADR 0005: Recovering from missed IR commands

- Status: Accepted
- Date: 2026-11-21
- Amends: [ADR 0002](0002-safety-layer-and-control-api.md) (compressor rule for manual commands)

## Context

IR is one-way (ADR 0002). During the first test on a real air conditioner (a Casper unit, 20-11) the AC sometimes missed a frame while the gateway believed it had been executed. The expected state was then wrong, and the safety timers were computed from transitions that never happened:

1. The user sends *on*; the AC misses it; the gateway now believes the AC is on.
2. The user sends *off* to try again; the gateway records a power-off and starts the 180 s `COMPRESSOR_MIN_OFF` timer.
3. The user sends *on*; it is rejected for up to 3 minutes, although the compressor never ran.

The only ways out were to wait or to press the original remote. Both are confusing, and the second needs the remote.

How comparable products handle this:

- Most split air conditioners protect their own compressor with a restart delay of about 3 minutes; the original remote never blocks the user.
- IR-bridge products (for example Sensibo) do not block manual commands and offer a way to correct the app's state without sending anything.

## Decision

Three small tools, all for people only (app key):

1. **Resend** (`POST /rooms/{room}/commands/resend`). Sends the expected state again. AC IR frames carry the *whole* state, so a resend is harmless if the AC already has it and fixes it if the AC missed it. It is not a state change, so it does not start the compressor timer. Logged with code `RESEND`; normal rate limit applies.
2. **Sync** (`PUT /rooms/{room}/ac-state`). The user states what the AC is actually doing; nothing is sent. Clears `uncertain`, starts the app auto-hold so automation does not immediately overwrite the correction, and does **not** touch `last_on_ts` / `last_off_ts` (a sync is not a power transition, and we do not know when the real one happened). Logged with verdict `sync`, code `STATE_SYNC`.
3. **Confirmed early start.** For manual commands `COMPRESSOR_MIN_OFF` becomes a question instead of a ban: the API answers `409` with `can_confirm: true`; resending the command with `confirm: true` is allowed and logged as `EARLY_START_CONFIRMED`. The rate limit still applies. Automatic commands are unchanged: confirmation is refused for the automation key (`403 CONFIRM_NOT_ALLOWED`) and ignored by `safety.evaluate()` for `rule`/`ai`.

The dashboard shows the question inline ("Máy nén vừa tắt… Vẫn bật?") and has a collapsible "Điều hòa không làm theo?" section with *Gửi lại lệnh* and *Thực tế điều hòa đang tắt/bật*.

## Consequences

- A person can recover from a missed frame in one tap, without the original remote and without waiting.
- The compressor rule still protects against automation, which is where rapid cycling would come from.
- A person can now restart the compressor early by confirming. The AC's own restart delay remains the last line of defence; units without one are not protected against a user who confirms repeatedly. Acceptable for manual use and documented in the dashboard text.
- A wrong sync (user reports the wrong state) is corrected by the next command or remote press, as before.
- Real feedback (a current clamp on the AC supply, or detecting the temperature drop after power-on) would remove the guesswork; left as future work.
