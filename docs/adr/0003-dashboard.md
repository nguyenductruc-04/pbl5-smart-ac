# ADR 0003: Dashboard served by the gateway, no build step, no external resources

- Status: Accepted
- Date: 2026-11-17

## Context

Users need to see the room and control the air conditioner from a phone or laptop. Constraints specific to this system:

- The Pi may have **no Internet**: when the home Wi-Fi is down it runs the backup access point (ADR 0001). The dashboard must still load there.
- One developer, and the Pi is the only server. A separate front-end toolchain (Node, bundler, framework upgrades) is a maintenance cost with little benefit for one page.
- The API key lives in the browser, so script injection would leak it.

## Decision

- A single-page dashboard in `gateway/web/` (HTML, CSS, one JavaScript file), served by the same FastAPI process at `/`. No framework, no bundler: what is in the repository is what the browser runs.
- **Everything is local**: the font (Be Vietnam Pro, SIL OFL) is bundled, charts are drawn as SVG by ~100 lines of code. No CDN.
- A strict Content-Security-Policy (`default-src 'self'`, no inline script or style) on every response except the generated API docs. Dynamic text is written with `textContent` only. A test enforces both.
- The dashboard is an ordinary API client using the **app key**, entered once and kept in `localStorage`. It has no privileges the API does not give that key.
- **Polling** every 3 s for room state (paused while the tab is hidden), with countdowns interpolated locally. No WebSocket: one extra request per 3 s is negligible on a LAN and polling recovers from network changes by itself.
- Commands are **coalesced**: rapid taps on +/− become one command with the final value, paced to the Safety Layer's rate limit so the UI never triggers `RATE_LIMIT` itself. The UI is optimistic and reverts if the gateway refuses, showing the reason in plain language.
- Charts use a server-side downsampling endpoint (`/telemetry/series`), so seven days of 30-second samples arrive as a few hundred points. Gaps (node offline) are drawn as gaps.

- **Comfort votes as labels.** The room with the node has no air conditioner, so manual AC adjustments cannot serve as training labels for Milestone 6. The dashboard records a three-point thermal preference vote ("want it cooler / comfortable / want it warmer"), the question format used in thermal comfort field studies such as the ASHRAE Global Thermal Comfort Database II. Each vote stores the latest temperature, humidity, presence and expected AC state; votes are refused when the latest reading is older than 120 s, guarded against double taps, and can be undone for 120 s.

## Consequences and known limitations

- Up to 3 s delay before a remote press or a change from another device appears.
- No automated browser tests in CI. The Python tests cover serving, CSP and the series endpoint; the interaction flows were verified manually with a headless browser against a simulated node.
- Plain HTTP and a static key: LAN, backup AP or Tailscale only (same limitation as ADR 0002). Browsers do not allow service workers on plain HTTP, so there is no offline app shell; "Add to Home screen" works as a shortcut.
- Votes are voluntary, so they may cluster around uncomfortable moments. The dashboard explicitly asks for votes when comfortable too; the class balance must be checked before training.
- A stolen phone with the saved key can control the AC until the key in `gateway/.env` is rotated.
