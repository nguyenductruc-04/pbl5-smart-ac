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
