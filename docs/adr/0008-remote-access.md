# ADR 0008: Remote access through Cloudflare Tunnel

- Status: Accepted
- Date: 2026-11-23

## Context

The gateway serves the dashboard and API on the home network (`http://<Pi>:8000`) and on its backup network (`http://10.42.0.1:8000`). A phone on mobile data cannot reach either: the Pi has a private address behind the router's NAT, and many Vietnamese ISPs add carrier-grade NAT, so even port forwarding often fails. Commercial products (LG ThinQ, Daikin) solve this with a vendor cloud that both the device and the app connect out to.

Options considered:

| Option | Works on 4G | Product-like | Cost / effort |
|---|---|---|---|
| Port forwarding | Not behind CGNAT; plain HTTP exposed | No | Router setup, unsafe |
| Tailscale / VPN | Yes | No: every user installs a VPN and is invited | Free, no code |
| Own cloud relay (MQTT broker or server on a VPS) | Yes | Yes | Server to run and secure, accounts to sync |
| **Cloudflare Tunnel** | Yes, also behind CGNAT | Yes: one HTTPS address for everyone | Domain (~5–12 USD/year), no server, little code |

## Decision

- `cloudflared` on the Pi keeps an outbound connection to Cloudflare. Public hostname `ac.<domain>` maps to `http://localhost:8000`. Cloudflare terminates HTTPS with its own certificate; no inbound port is opened.
- The gateway does not know about the tunnel except:
  - `PUBLIC_URL` in `.env`, reported by `GET /setup/status` so the app learns the address while on the home network (no domain compiled into the app);
  - requests carrying `CF-Connecting-IP` (always set by Cloudflare, so it cannot be removed by a remote client) are refused at `POST /setup` with `SETUP_LOCAL_ONLY`. Claiming a new or reset Pi needs a phone on its network, which keeps the "physical access" assumption of ADR 0007.
- Uvicorn trusts `X-Forwarded-*` from `127.0.0.1` (its default), so behind the tunnel the scheme is `https` and pairing links use the public address.
- The app probes, in parallel, the last home address, the backup address and the public address, and uses the first one that answers in that order of preference. When polling fails twice it probes again, so moving between Wi-Fi, mobile data and the backup network needs no new sign-in: it is the same server and the same session.

## Consequences

- The sign-in page is reachable from the Internet. Defences already in place: scrypt hashes, per-name lockout, approval of new accounts, first setup only on the local network. HTTPS removes the sniffing risk of plain HTTP on that path.
- Traffic leaves the house and comes back through Cloudflare: about 0.1–0.3 s more per command, and it needs the home Internet link. The local paths stay available and are preferred.
- Cloudflare can see the traffic it terminates. Acceptable for a student project; an own relay or end-to-end encryption would be needed for a product with stronger privacy requirements.
- The tunnel token in `/etc/cloudflared` is a secret: whoever has it can serve the hostname.
