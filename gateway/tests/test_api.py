"""Test REST API dau-cuoi trong tien trinh: HTTP -> CommandService -> Safety Layer -> node gia."""
import json

import pytest
from fastapi.testclient import TestClient

import api
import control
import store

KEY = "app-key-0123456789abcdef"
AUTO_KEY = "auto-key-0123456789abcdef"
H = {"X-API-Key": KEY}
HA = {"X-API-Key": AUTO_KEY}
CMD = "/api/v1/rooms/room01/commands"


@pytest.fixture
def client(gateway, clock):
    gateway.handle_status("room01", clock(), "online")
    service = control.CommandService(gateway, clock=clock, timeout_s=0.05)
    app = api.create_app(gateway, service, api_key=KEY, automation_key=AUTO_KEY, clock=clock)
    with TestClient(app) as c:
        c.gateway = gateway
        yield c


def code(resp):
    return resp.json()["error"]["code"]


# ------------------------------------------------------------------ khoi dong & xac thuc
def test_refuses_to_start_without_api_key(gateway):
    with pytest.raises(SystemExit):
        api.create_app(gateway, api_key="")
    with pytest.raises(SystemExit):
        api.create_app(gateway, api_key=KEY, automation_key=KEY)


def test_health_needs_no_key(client):
    r = client.get("/api/v1/health")
    assert r.status_code == 200 and r.json()["mqtt_connected"] is True


def test_health_reports_broker_loss(client):
    client.gateway.client.connected = False
    assert client.get("/api/v1/health").status_code == 503


@pytest.mark.parametrize("headers", [{}, {"X-API-Key": "wrong"}])
def test_everything_else_needs_a_key(client, headers):
    for method, path in [("get", "/api/v1/rooms"), ("get", "/api/v1/rooms/room01"),
                         ("get", "/api/v1/policy"), ("delete", "/api/v1/rooms/room01/auto-hold")]:
        r = getattr(client, method)(path, headers=headers)
        assert (r.status_code, code(r)) == (401, "UNAUTHORIZED")
    assert client.post(CMD, json={"power": "on"}, headers=headers).status_code == 401
    assert client.gateway.client.published == []


def test_unknown_room_is_404_and_bad_room_name_is_422(client):
    assert code(client.get("/api/v1/rooms/room99", headers=H)) == "ROOM_NOT_FOUND"
    assert client.post("/api/v1/rooms/room99/commands", json={"power": "on"}, headers=H).status_code == 404
    assert client.get("/api/v1/rooms/a+b", headers=H).status_code == 422


# ------------------------------------------------------------------ lenh thu cong
def test_command_is_executed_and_state_updated(client):
    r = client.post(CMD, json={"power": "on", "temp": 24}, headers=H)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "executed" and body["source"] == "app"
    assert body["requested"] == {"power": "on", "mode": "cool", "temp": 24, "fan": "auto"}
    assert body["room"]["ac"]["temp"] == 24 and body["room"]["ac"]["uncertain"] is False
    assert body["room"]["safety"]["auto_hold_source"] == "app"
    topic, sent = client.gateway.client.published[0]
    assert topic == "home/room01/command"
    assert {k: sent[k] for k in ("power", "mode", "temp", "fan", "source")} == {
        "power": "on", "mode": "cool", "temp": 24, "fan": "auto", "source": "app"}


def test_partial_command_keeps_other_fields(client, clock):
    client.post(CMD, json={"power": "on", "mode": "dry", "temp": 25, "fan": "high"}, headers=H)
    clock.advance(10)
    r = client.post(CMD, json={"temp": 23}, headers=H)
    assert r.json()["requested"] == {"power": "on", "mode": "dry", "temp": 23, "fan": "high"}


@pytest.mark.parametrize("body", [{}, {"temp": "hot"}, {"power": "maybe"}, {"temp": 24, "swing": True},
                                  {"temp": 24.5}])
def test_malformed_body_is_422(client, body):
    assert client.post(CMD, json=body, headers=H).status_code == 422
    assert client.gateway.client.published == []


def test_temp_out_of_policy_range_is_422(client):
    r = client.post(CMD, json={"power": "on", "temp": 12}, headers=H)
    assert (r.status_code, code(r)) == (422, "TEMP_OUT_OF_RANGE")


def test_rate_limit_is_429_with_retry_after(client, clock):
    client.post(CMD, json={"power": "on"}, headers=H)
    clock.advance(0.5)
    r = client.post(CMD, json={"temp": 22}, headers=H)
    assert (r.status_code, code(r), r.headers["Retry-After"]) == (429, "RATE_LIMIT", "2")
    assert client.post(CMD, json={"power": "off"}, headers=H).status_code == 200   # tat luon duoc


def test_compressor_protection_is_409_then_allowed(client, clock):
    client.post(CMD, json={"power": "on"}, headers=H)
    clock.advance(10)
    client.post(CMD, json={"power": "off"}, headers=H)
    clock.advance(30)
    r = client.post(CMD, json={"power": "on"}, headers=H)
    assert (r.status_code, code(r), r.json()["error"]["retry_after_s"]) == (409, "COMPRESSOR_MIN_OFF", 150)
    assert client.get("/api/v1/rooms/room01", headers=H).json()["safety"]["compressor_ready_in_s"] == 150
    clock.advance(150)
    assert client.post(CMD, json={"power": "on"}, headers=H).status_code == 200


def test_early_restart_can_be_confirmed_by_a_person(client, clock):
    client.post(CMD, json={"power": "on"}, headers=H)
    clock.advance(10)
    client.post(CMD, json={"power": "off"}, headers=H)
    clock.advance(30)
    r = client.post(CMD, json={"power": "on"}, headers=H)
    assert (r.status_code, code(r), r.json()["error"]["can_confirm"]) == (409, "COMPRESSOR_MIN_OFF", True)
    r = client.post(CMD, json={"power": "on", "confirm": True}, headers=H)
    assert (r.status_code, r.json()["code"]) == (200, "EARLY_START_CONFIRMED")
    assert r.json()["room"]["ac"]["power"] == "on"


def test_automation_key_cannot_confirm(client, clock):
    r = client.post(CMD, json={"power": "on", "source": "ai", "confirm": True}, headers=HA)
    assert (r.status_code, code(r)) == (403, "CONFIRM_NOT_ALLOWED")
    assert client.gateway.client.published == []


def test_resend_publishes_the_expected_state_again(client, clock):
    client.post(CMD, json={"power": "on", "temp": 24}, headers=H)
    clock.advance(10)
    r = client.post(CMD + "/resend", headers=H)
    assert (r.status_code, r.json()["code"], r.json()["status"]) == (200, "RESEND", "executed")
    (_, first), (_, again) = client.gateway.client.published
    assert {k: again[k] for k in ("power", "mode", "temp", "fan")} == {
        k: first[k] for k in ("power", "mode", "temp", "fan")}
    assert again["cmd_id"] != first["cmd_id"]


def test_resend_does_not_restart_compressor_timer(client, clock):
    client.post(CMD, json={"power": "on"}, headers=H)
    clock.advance(10)
    client.post(CMD, json={"power": "off"}, headers=H)
    clock.advance(30)
    assert client.post(CMD + "/resend", headers=H).status_code == 200      # gui lai lenh tat
    assert client.get("/api/v1/rooms/room01", headers=H).json()["safety"]["compressor_ready_in_s"] == 150


def test_resend_needs_a_known_state_and_a_person(client):
    r = client.post(CMD + "/resend", headers=H)
    assert (r.status_code, code(r)) == (409, "NO_STATE")
    assert client.post(CMD + "/resend", headers=HA).status_code == 403
    assert client.gateway.client.published == []


def test_sync_fixes_state_without_sending_ir(client, clock):
    client.post(CMD, json={"power": "on", "temp": 24}, headers=H)
    clock.advance(10)
    r = client.put("/api/v1/rooms/room01/ac-state", json={"power": "off"}, headers=H)
    assert r.status_code == 200
    ac = r.json()["ac"]
    assert (ac["power"], ac["temp"], ac["source"], ac["uncertain"]) == ("off", 24, "sync", False)
    assert len(client.gateway.client.published) == 1                     # khong phat IR
    assert r.json()["safety"]["compressor_ready_in_s"] == 0               # khong bat dong ho may nen
    assert client.post(CMD, json={"power": "on"}, headers=H).status_code == 200
    log = client.get("/api/v1/rooms/room01/decisions", headers=H).json()["items"]
    assert any(d["verdict"] == "sync" and d["code"] == "STATE_SYNC" for d in log)


def test_sync_clears_uncertain_and_holds_automation(client, clock):
    client.gateway.client.node = "silent"
    client.post(CMD, json={"power": "on"}, headers=H)                     # het han -> khong chac chan
    client.gateway.client.node = "ok"
    clock.advance(5)
    r = client.put("/api/v1/rooms/room01/ac-state", json={"power": "on", "temp": 25}, headers=H)
    assert r.json()["ac"]["uncertain"] is False
    assert r.json()["safety"]["auto_hold_remaining_s"] > 0


def test_sync_validation_and_permissions(client):
    assert client.put("/api/v1/rooms/room01/ac-state", json={}, headers=H).status_code == 422
    assert client.put("/api/v1/rooms/room01/ac-state", json={"power": "maybe"}, headers=H).status_code == 422
    assert client.put("/api/v1/rooms/room01/ac-state", json={"power": "on"}, headers=HA).status_code == 403
    assert client.put("/api/v1/rooms/room01/ac-state", json={"power": "on"}).status_code == 401


def test_parallel_commands_cannot_bypass_rate_limit(client):
    """10 lenh den cung luc: dung 1 lenh duoc gui, 9 lenh bi RATE_LIMIT, khong lenh nao loi 500."""
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(10) as pool:
        codes = list(pool.map(
            lambda t: client.post(CMD, json={"power": "on", "temp": t}, headers=H).status_code,
            range(16, 26)))
    assert sorted(codes) == [200] + [429] * 9
    assert len(client.gateway.client.published) == 1


# ------------------------------------------------------------------ mat ket noi
def test_node_offline_is_503_and_nothing_is_published(client, clock):
    client.gateway.handle_status("room01", clock(), "offline")
    r = client.post(CMD, json={"power": "on"}, headers=H)
    assert (r.status_code, code(r)) == (503, "NODE_OFFLINE")
    assert client.gateway.client.published == []


def test_broker_down_is_503_and_nothing_is_published(client):
    client.gateway.client.connected = False
    r = client.post(CMD, json={"power": "on"}, headers=H)
    assert (r.status_code, code(r)) == (503, "BROKER_UNAVAILABLE")
    assert client.gateway.client.published == []


def test_node_timeout_is_504_and_state_becomes_uncertain(client, clock):
    client.post(CMD, json={"power": "on"}, headers=H)
    clock.advance(10)
    client.gateway.client.node = "silent"
    r = client.post(CMD, json={"temp": 22}, headers=H)
    assert (r.status_code, code(r)) == (504, "NODE_TIMEOUT")
    ac = client.get("/api/v1/rooms/room01", headers=H).json()["ac"]
    assert (ac["temp"], ac["uncertain"]) == (26, True)


def test_late_result_after_timeout_still_syncs_state(client, clock):
    client.gateway.client.node = "silent"
    client.post(CMD, json={"power": "on", "temp": 22}, headers=H)
    cmd_id = client.gateway.client.published[0][1]["cmd_id"]
    client.gateway.handle_result("room01", clock() + 8, json.dumps({"cmd_id": cmd_id, "ok": True}))
    ac = client.get("/api/v1/rooms/room01", headers=H).json()["ac"]
    assert (ac["temp"], ac["uncertain"]) == (22, False)


def test_node_error_is_502_and_state_unchanged(client):
    client.gateway.client.node = "error"
    r = client.post(CMD, json={"power": "on"}, headers=H)
    assert (r.status_code, code(r)) == (502, "NODE_ERROR")
    assert client.get("/api/v1/rooms/room01", headers=H).json()["ac"] is None


# ------------------------------------------------------------------ uu tien nguoi dung
def fresh_telemetry(client, clock, presence=True):
    client.gateway.handle_telemetry(
        "room01", clock(), json.dumps({"temp": 28.5, "hum": 60, "presence": presence}))


def test_source_comes_from_the_key_not_the_body(client):
    r = client.post(CMD, json={"power": "on", "source": "ai"}, headers=H)
    assert (r.status_code, code(r)) == (403, "SOURCE_NOT_ALLOWED")
    for body in ({"power": "on"}, {"power": "on", "source": "app"}):
        r = client.post(CMD, json=body, headers=HA)
        assert (r.status_code, code(r)) == (403, "SOURCE_NOT_ALLOWED")


def test_auto_blocked_after_app_command_until_hold_cleared(client, clock):
    client.post(CMD, json={"power": "on", "temp": 26}, headers=H)
    clock.advance(60)
    fresh_telemetry(client, clock)
    r = client.post(CMD, json={"temp": 27, "source": "ai"}, headers=HA)
    assert (r.status_code, code(r)) == (409, "MANUAL_HOLD")
    assert client.delete("/api/v1/rooms/room01/auto-hold", headers=HA).status_code == 403
    assert client.delete("/api/v1/rooms/room01/auto-hold", headers=H).status_code == 200
    r = client.post(CMD, json={"temp": 27, "source": "ai"}, headers=HA)
    assert r.status_code == 200 and r.json()["source"] == "ai"
    assert r.json()["room"]["safety"]["auto_hold_remaining_s"] == 0      # AI khong tao hold


def test_remote_press_blocks_auto_for_an_hour(client, clock):
    ir = {"protocol": "DAIKIN", "power": "on", "mode": "cool", "temp": 25, "fan": "auto"}
    client.gateway.handle_ir_event("room01", clock(), json.dumps(ir))
    clock.advance(3599)
    fresh_telemetry(client, clock)
    assert code(client.post(CMD, json={"temp": 26, "source": "rule"}, headers=HA)) == "MANUAL_HOLD"
    clock.advance(1)
    assert client.post(CMD, json={"temp": 26, "source": "rule"}, headers=HA).status_code == 200


def test_auto_no_change_is_skipped_without_sending(client, clock):
    client.post(CMD, json={"power": "on", "temp": 26}, headers=H)
    clock.advance(4000)
    fresh_telemetry(client, clock)
    n = len(client.gateway.client.published)
    r = client.post(CMD, json={"temp": 26, "source": "rule"}, headers=HA)
    assert r.status_code == 200 and r.json()["status"] == "skipped" and r.json()["cmd_id"] is None
    assert len(client.gateway.client.published) == n


def test_auto_blocked_after_node_was_offline(client, clock):
    client.post(CMD, json={"power": "on", "temp": 26}, headers=H)
    clock.advance(4000)
    client.gateway.handle_status("room01", clock(), "offline")
    client.gateway.handle_status("room01", clock(), "online")
    fresh_telemetry(client, clock)
    assert code(client.post(CMD, json={"temp": 27, "source": "ai"}, headers=HA)) == "STATE_UNCERTAIN"


# ------------------------------------------------------------------ doc du lieu
def test_room_state_and_listing(client, clock):
    fresh_telemetry(client, clock, presence=None)
    clock.advance(7)
    assert client.get("/api/v1/rooms", headers=H).json()["rooms"][0]["room"] == "room01"
    s = client.get("/api/v1/rooms/room01", headers=H).json()
    assert s["node"]["status"] == "online" and s["ac"] is None
    assert (s["telemetry"]["temp"], s["telemetry"]["age_s"], s["telemetry"]["presence"]) == (28.5, 7, None)


def test_history_endpoints(client, clock):
    fresh_telemetry(client, clock)
    client.post(CMD, json={"power": "on"}, headers=H)
    client.post(CMD, json={"temp": 22}, headers=H)            # bi RATE_LIMIT
    ir = {"protocol": "DAIKIN", "power": "off", "mode": "cool", "temp": 25, "fan": "auto"}
    client.gateway.handle_ir_event("room01", clock(), json.dumps(ir))

    cmds = client.get(CMD, headers=H).json()["items"]
    assert len(cmds) == 1 and cmds[0]["ok"] is True and cmds[0]["requested"]["power"] == "on"
    decisions = client.get("/api/v1/rooms/room01/decisions", headers=H).json()["items"]
    assert [(d["verdict"], d["code"]) for d in decisions] == [("reject", "RATE_LIMIT"), ("allow", "OK")]
    assert decisions[1]["cmd_id"] == cmds[0]["cmd_id"]
    assert client.get("/api/v1/rooms/room01/ir-events", headers=H).json()["items"][0]["power"] == "off"
    tel = client.get("/api/v1/rooms/room01/telemetry?limit=5", headers=H).json()["items"]
    assert len(tel) == 1 and tel[0]["hum"] == 60
    assert client.get("/api/v1/rooms/room01/telemetry?limit=0", headers=H).status_code == 422


def test_policy_endpoint(client):
    assert client.get("/api/v1/policy", headers=H).json()["min_off_s"] == 180.0


def test_decision_log_records_requested_state(client):
    client.post(CMD, json={"power": "on", "temp": 12}, headers=H)
    row = store.decision_history(client.gateway.db, "room01", 1)[0]
    assert (row["code"], row["requested"]["temp"], row["cmd_id"]) == ("TEMP_OUT_OF_RANGE", 12, None)


# ------------------------------------------------------------------ bieu do & dashboard
def test_series_buckets_and_orders_oldest_first(client, clock):
    for i in range(120):                                   # 1 gio du lieu, 30 s mot mau
        client.gateway.handle_telemetry(
            "room01", clock() - 3600 + i * 30, json.dumps({"temp": 26 + i / 60, "hum": 60}))
    r = client.get("/api/v1/rooms/room01/telemetry/series?hours=1&points=12", headers=H).json()
    items = r["items"]
    assert r["bucket_s"] == 300 and len(items) == 12
    assert [p["ts"] for p in items] == sorted(p["ts"] for p in items)
    assert sum(p["n"] for p in items) == 120
    assert items[0]["temp"] < items[-1]["temp"] and items[0]["hum"] == 60


def test_series_empty_and_validation(client):
    assert client.get("/api/v1/rooms/room01/telemetry/series", headers=H).json()["items"] == []
    assert client.get("/api/v1/rooms/room01/telemetry/series?points=5", headers=H).status_code == 422
    assert client.get("/api/v1/rooms/room01/telemetry/series?hours=0", headers=H).status_code == 422
    assert client.get("/api/v1/rooms/room01/telemetry/series").status_code == 401


def test_dashboard_is_served_with_strict_csp(client):
    r = client.get("/")
    assert r.status_code == 200 and "<title>" in r.text
    csp = r.headers["Content-Security-Policy"]
    assert "script-src 'self'" in csp and "unsafe-inline" not in csp
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    for path in ("/app.js", "/style.css", "/icon.svg", "/manifest.webmanifest",
                 "/fonts/be-vietnam-pro-vietnamese-400-normal.woff2"):
        assert client.get(path).status_code == 200, path


def test_dashboard_has_no_inline_code_or_external_hosts():
    """CSP cam script/style noi tuyen va moi may chu ngoai: kiem tra ngay tren ma nguon."""
    import re
    html = (api.WEB_DIR / "index.html").read_text(encoding="utf-8")
    assert not re.search(r"<script(?![^>]*\bsrc=)", html) and "<style" not in html
    assert not re.search(r"\son\w+=|\sstyle=", html)
    for name in ("index.html", "style.css", "app.js", "manifest.webmanifest"):
        text = (api.WEB_DIR / name).read_text(encoding="utf-8")
        assert not re.search(r"https?://(?!www\.w3\.org/)", text), name
    assert "innerHTML" not in (api.WEB_DIR / "app.js").read_text(encoding="utf-8").replace("(khong innerHTML)", "")


def test_api_docs_still_work_and_api_is_not_cached(client):
    assert client.get("/docs").status_code == 200
    assert "Content-Security-Policy" not in client.get("/docs").headers
    assert client.get("/api/v1/health").headers["Cache-Control"] == "no-store"
    assert client.get("/api/v1/nope").status_code == 404


def test_snapshot_tells_dashboard_whether_automation_exists(client, gateway):
    assert client.get("/api/v1/rooms/room01", headers=H).json()["safety"]["automation_enabled"] is True
    app = api.create_app(gateway, api_key=KEY, automation_key="")
    with TestClient(app) as c:
        assert c.get("/api/v1/rooms/room01", headers=H).json()["safety"]["automation_enabled"] is False


# ------------------------------------------------------------------ phieu cam nhan (nhan cho M6)
VOTE = "/api/v1/rooms/room01/comfort"


def test_vote_is_stored_with_context(client, clock):
    fresh_telemetry(client, clock, presence=True)
    client.post(CMD, json={"power": "on", "temp": 25}, headers=H)
    clock.advance(30)
    r = client.post(VOTE, json={"vote": "cooler"}, headers=H)
    assert r.status_code == 201
    v = r.json()
    assert (v["vote"], v["temp"], v["hum"], v["presence"]) == ("cooler", 28.5, 60, True)
    assert (v["telemetry_age_s"], v["ac_power"], v["ac_temp"], v["ac_uncertain"]) == (30, "on", 25, False)
    row = client.gateway.db.execute("SELECT vote FROM comfort_votes").fetchone()
    assert row == (-1,)                                         # luu dang so cho mo hinh


def test_vote_without_known_ac_state(client, clock):
    fresh_telemetry(client, clock, presence=None)
    v = client.post(VOTE, json={"vote": "comfortable"}, headers=H).json()
    assert (v["vote"], v["presence"], v["ac_power"], v["ac_uncertain"]) == ("comfortable", None, None, None)


def test_vote_rejected_without_fresh_telemetry(client, clock):
    r = client.post(VOTE, json={"vote": "warmer"}, headers=H)
    assert (r.status_code, code(r)) == (409, "TELEMETRY_STALE")
    fresh_telemetry(client, clock)
    clock.advance(121)
    assert code(client.post(VOTE, json={"vote": "warmer"}, headers=H)) == "TELEMETRY_STALE"
    assert client.gateway.db.execute("SELECT COUNT(*) FROM comfort_votes").fetchone() == (0,)


def test_double_tap_is_rejected(client, clock):
    fresh_telemetry(client, clock)
    assert client.post(VOTE, json={"vote": "cooler"}, headers=H).status_code == 201
    clock.advance(2)
    r = client.post(VOTE, json={"vote": "cooler"}, headers=H)
    assert (r.status_code, code(r), r.headers["Retry-After"]) == (429, "VOTE_TOO_FAST", "3")
    clock.advance(3)
    assert client.post(VOTE, json={"vote": "warmer"}, headers=H).status_code == 201


@pytest.mark.parametrize("body", [{}, {"vote": "hot"}, {"vote": "cooler", "temp": 20}])
def test_bad_vote_is_422(client, clock, body):
    fresh_telemetry(client, clock)
    assert client.post(VOTE, json=body, headers=H).status_code == 422


def test_only_people_can_vote_or_undo(client, clock):
    fresh_telemetry(client, clock)
    r = client.post(VOTE, json={"vote": "cooler"}, headers=HA)
    assert (r.status_code, code(r)) == (403, "FORBIDDEN")
    vote_id = client.post(VOTE, json={"vote": "cooler"}, headers=H).json()["id"]
    assert client.delete(f"{VOTE}/{vote_id}", headers=HA).status_code == 403
    assert client.post(VOTE, json={"vote": "cooler"}).status_code == 401


def test_undo_within_window_only(client, clock):
    fresh_telemetry(client, clock)
    first = client.post(VOTE, json={"vote": "cooler"}, headers=H).json()["id"]
    clock.advance(60)
    assert client.delete(f"{VOTE}/{first}", headers=H).json() == {"deleted": first}
    assert code(client.delete(f"{VOTE}/{first}", headers=H)) == "VOTE_NOT_FOUND"
    fresh_telemetry(client, clock)
    second = client.post(VOTE, json={"vote": "warmer"}, headers=H).json()["id"]
    clock.advance(121)
    assert code(client.delete(f"{VOTE}/{second}", headers=H)) == "UNDO_EXPIRED"


def test_vote_history_newest_first_and_since(client, clock):
    fresh_telemetry(client, clock)
    for vote in ("cooler", "comfortable", "warmer"):
        client.post(VOTE, json={"vote": vote}, headers=H)
        clock.advance(10)
    items = client.get(VOTE, headers=H).json()["items"]
    assert [i["vote"] for i in items] == ["warmer", "comfortable", "cooler"]
    since = items[1]["ts"]
    assert len(client.get(f"{VOTE}?since={since}", headers=H).json()["items"]) == 2


# ------------------------------------------------------------------ goi y (M6)
SUG = "/api/v1/rooms/room01/suggestion"


def tel(client, clock, temp, presence=True, hum=65, at=None):
    client.gateway.handle_telemetry("room01", clock() if at is None else at,
                                    json.dumps({"temp": temp, "hum": hum, "presence": presence}))


def test_suggestion_without_data(client):
    s = client.get(SUG, headers=H).json()
    assert (s["action"], s["reason"], s["comfort"], s["auto"]) == ("none", "NO_DATA", None, False)
    assert s["model"]["votes"] == 0 and s["model"]["personal"] is False
    assert "ASHRAE" in s["model"]["prior"]


def test_hot_room_suggests_turning_on(client, clock):
    tel(client, clock, 31.0)
    s = client.get(SUG, headers=H).json()
    assert (s["action"], s["reason"]) == ("turn_on", "TOO_WARM")
    assert s["target"] == {"power": "on", "mode": "cool", "temp": s["setpoint"], "fan": "auto"}
    assert s["comfort"]["cooler"] > 0.6 and s["comfort_band"][0] < s["comfort_band"][1]


def test_suggestion_is_read_only(client, clock):
    tel(client, clock, 31.0)
    client.get(SUG, headers=H)
    assert client.gateway.client.published == []
    assert store.decision_history(client.gateway.db, "room01", 5) == []


def test_votes_personalize_the_suggestion(client, clock):
    before = client.get(SUG, headers=H).json()["neutral_temp"]
    for i in range(12):                      # nguoi nay van muon mat hon o 24-25 do
        tel(client, clock, 24.0 + (i % 2))
        assert client.post("/api/v1/rooms/room01/comfort", json={"vote": "cooler"}, headers=H).status_code == 201
        clock.advance(6)
    s = client.get(SUG, headers=H).json()
    assert s["model"]["votes"] == 12 and s["model"]["personal"] is True
    assert s["model"]["shift_c"] < 0 and s["neutral_temp"] < before


def test_long_empty_room_with_ac_on_suggests_off(client, clock):
    client.post(CMD, json={"power": "on", "temp": 25}, headers=H)
    tel(client, clock, 27.0, presence=True)
    clock.advance(16 * 60)
    tel(client, clock, 27.0, presence=False)
    s = client.get(SUG, headers=H).json()
    assert (s["action"], s["target"]["power"]) == ("turn_off", "off")


def test_auto_step_respects_safety_layer(client, clock):
    import advisor
    adv = client.app.state.advisor
    svc = client.app.state.service
    tel(client, clock, 31.0)
    db = client.gateway.db
    assert advisor.auto_step(adv, svc, db, clock()) == []          # chua biet trang thai -> STATE_UNCERTAIN
    client.post(CMD, json={"power": "off"}, headers=H)             # nguoi dung dong bo trang thai
    clock.advance(200)
    tel(client, clock, 31.0)
    assert advisor.auto_step(adv, svc, db, clock()) == []          # MANUAL_HOLD 30 phut
    client.delete("/api/v1/rooms/room01/auto-hold", headers=H)
    done = advisor.auto_step(adv, svc, db, clock())
    assert len(done) == 1 and done[0][1].status == "executed"
    assert client.gateway.client.published[-1][1]["source"] == "ai"
    codes = [d["code"] for d in store.decision_history(db, "room01", 10)]
    assert "STATE_UNCERTAIN" not in codes and "MANUAL_HOLD" not in codes     # xem truoc khong ghi nhat ky
    assert advisor.auto_step(adv, svc, db, clock()) == []          # da dat dung -> khong lam gi them


# ------------------------------------------------------------------ ghep thiet bi bang QR (v0.9.0)
PAIR = "/api/v1/pairing"


def test_pairing_code_logs_in_a_new_device_once(client):
    r = client.post(PAIR, headers=H)
    assert r.status_code == 201
    body = r.json()
    assert body["url"].endswith(f"/#pair={body['code']}") and body["expires_in_s"] == 300
    assert body["qr"].startswith("data:image/svg+xml")
    r = client.post(PAIR + "/claim", json={"code": body["code"]})            # khong can khoa
    assert (r.status_code, r.json()["api_key"]) == (200, KEY)
    r = client.post(PAIR + "/claim", json={"code": body["code"]})            # dung lan hai
    assert (r.status_code, code(r)) == (410, "PAIR_INVALID")


def test_pairing_code_expires(client, clock):
    c = client.post(PAIR, headers=H).json()["code"]
    clock.advance(301)
    assert client.post(PAIR + "/claim", json={"code": c}).status_code == 410


def test_only_people_can_create_pairing_codes(client):
    assert client.post(PAIR).status_code == 401
    assert client.post(PAIR, headers=HA).status_code == 403


def test_guessing_pairing_codes_is_rate_limited(client):
    for _ in range(10):
        assert client.post(PAIR + "/claim", json={"code": "wrong-code-123"}).status_code == 410
    good = client.post(PAIR, headers=H).json()["code"]
    r = client.post(PAIR + "/claim", json={"code": good})
    assert (r.status_code, code(r)) == (429, "PAIR_TOO_MANY")


# ------------------------------------------------------------------ che do mang (v0.9.0)
NET = "/api/v1/system/network"


@pytest.fixture
def net_files(tmp_path, monkeypatch):
    import netmode
    monkeypatch.setattr(netmode, "MODE_FILE", tmp_path / "network_mode")
    monkeypatch.setattr(netmode, "STATUS_FILE", tmp_path / "network_status.json")
    monkeypatch.setenv("NETWORK_MODE", "auto")
    return netmode


def test_network_mode_defaults_to_env_and_reports_missing_netwatch(client, net_files):
    r = client.get(NET, headers=H).json()
    assert (r["mode"], r["chosen"], r["default"], r["status"]) == ("auto", None, "auto", None)
    assert r["ap_ssid"] == "SmartAC-Backup" and r["ap_url"].startswith("http://10.42.0.1")


def test_person_can_switch_network_mode(client, net_files, clock):
    net_files.write_status({"mode": "auto", "state": "home", "connection": "Mai", "ts": clock()})
    r = client.put(NET, json={"mode": "standalone"}, headers=H)
    assert r.status_code == 200
    body = r.json()
    assert (body["mode"], body["chosen"]) == ("standalone", "standalone")
    assert body["status"]["running"] is True and body["status"]["mode"] == "auto"   # netwatch chua kip doc
    assert net_files.MODE_FILE.read_text().strip() == "standalone"


def test_switching_tells_nodes_to_follow_before_the_pi_moves(client, net_files, clock):
    net_files.write_status({"mode": "auto", "state": "home", "connection": "Mai", "ts": clock()})
    client.put(NET, json={"mode": "standalone"}, headers=H)
    assert client.gateway.client.config == [("home/room01/config", {"net": "backup"}, False)]

    net_files.write_status({"mode": "standalone", "state": "ap", "connection": "SmartAC-Backup", "ts": clock()})
    client.gateway.client.config.clear()
    client.put(NET, json={"mode": "auto"}, headers=H)
    assert client.gateway.client.config == [("home/room01/config", {"net": "home"}, False)]


def test_no_hint_when_the_network_does_not_change(client, net_files, clock):
    net_files.write_status({"mode": "auto", "state": "home", "connection": "Mai", "ts": clock()})
    client.put(NET, json={"mode": "home"}, headers=H)                     # van o Wi-Fi nha
    net_files.write_status({"mode": "standalone", "state": "ap", "connection": "SmartAC-Backup", "ts": clock()})
    client.put(NET, json={"mode": "standalone"}, headers=H)               # van o mang rieng
    assert client.gateway.client.config == []


def test_network_mode_validation_and_permissions(client, net_files):
    assert client.put(NET, json={"mode": "party"}, headers=H).status_code == 422
    assert client.put(NET, json={"mode": "home"}, headers=HA).status_code == 403
    assert client.put(NET, json={"mode": "home"}).status_code == 401
    assert not net_files.MODE_FILE.exists()


def test_health_reports_gateway_time(client, clock):
    assert client.get("/api/v1/health").json()["time"] == round(clock(), 1)
