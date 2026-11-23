"""Nhan dien va doi giao thuc IR cua dieu hoa (v0.11.0, ADR 0009)."""
import json

import pytest
from fastapi.testclient import TestClient

import api
import control
import irproto

KEY = "app-key-0123456789abcdef"
H = {"X-API-Key": KEY}
IR = "/api/v1/rooms/room01/ir"


@pytest.fixture
def client(gateway, clock):
    gateway.handle_status("room01", clock(), "online")
    service = control.CommandService(gateway, clock=clock, timeout_s=0.05)
    app = api.create_app(gateway, service, api_key=KEY, clock=clock, setup_code="ABCD-EFGH-JKMN",
                         device_id="d3v1ce00")
    with TestClient(app) as c:
        c.gateway = gateway
        yield c


def telemetry(g, clock, proto="DAIKIN", model=-1):
    g.handle_telemetry("room01", clock(), json.dumps({"temp": 28, "hum": 60, "ir_protocol": proto, "ir_model": model}))


def code(r):
    return r.json()["error"]["code"]


def test_node_reports_its_protocol_in_telemetry(client, clock):
    telemetry(client.gateway, clock)
    info = client.get(IR, headers=H).json()
    assert (info["protocol"], info["model"], info["confirmed"]) == ("DAIKIN", -1, False)
    assert "Daikin" in info["brands"]


def test_learn_mode_collects_what_the_node_hears(client, clock):
    telemetry(client.gateway, clock)
    r = client.post(IR + "/learn", json={"seconds": 60}, headers=H)
    assert r.json()["learn"]["active"] is True
    assert client.gateway.client.config[-1][1] == {"ir_learn": 60}
    g = client.gateway
    clock.advance(1)
    g.handle_ir_event("room01", clock(), json.dumps({"protocol": "UNKNOWN", "ac": False, "bits": 211, "learn": True}))
    clock.advance(1)
    for _ in range(2):
        g.handle_ir_event("room01", clock(), json.dumps(
            {"protocol": "COOLIX", "ac": True, "model": -1, "power": "on", "mode": "cool", "temp": 25,
             "fan": "auto", "learn": True}))
    info = client.get(IR, headers=H).json()
    assert [c["protocol"] for c in info["candidates"]] == ["COOLIX", "UNKNOWN"]   # dieu hoa len truoc
    assert info["candidates"][0]["count"] == 2 and info["candidates"][0]["last"]["temp"] == 25
    clock.advance(61)
    assert client.get(IR, headers=H).json()["learn"]["active"] is False


def test_non_ac_signal_does_not_touch_the_ac_state(client, clock):
    g = client.gateway
    client.post("/api/v1/rooms/room01/commands", json={"power": "on", "temp": 26}, headers=H)
    before = client.get("/api/v1/rooms/room01", headers=H).json()["ac"]
    g.handle_ir_event("room01", clock(), json.dumps({"protocol": "NEC", "ac": False, "bits": 32}))
    after = client.get("/api/v1/rooms/room01", headers=H).json()["ac"]
    assert after == before and after["uncertain"] is False


def test_switching_protocol_waits_for_the_node(client, clock):
    telemetry(client.gateway, clock)
    r = client.put(IR, json={"protocol": "coolix"}, headers=H)
    assert r.status_code == 200, r.text
    assert r.json()["protocol"] == "COOLIX" and r.json()["confirmed"] is False
    sent = client.gateway.client.config[-1][1]
    assert sent["ir"] == {"protocol": "COOLIX", "model": -1} and sent["cfg_id"].startswith("ir-")
    # remote cua giao thuc moi gio dong bo duoc trang thai, giao thuc cu thi khong
    assert irproto.expected_protocol(client.gateway.db, "room01") == "COOLIX"
    # ban telemetry gui TRUOC luc doi (con tren duong) khong duoc keo giao thuc ve cai cu
    clock.advance(2)
    telemetry(client.gateway, clock, proto="DAIKIN")
    assert client.get(IR, headers=H).json()["protocol"] == "COOLIX"
    clock.advance(30)
    telemetry(client.gateway, clock, proto="COOLIX")
    assert client.get(IR, headers=H).json()["protocol"] == "COOLIX"


def test_unsupported_protocol_is_refused_by_the_node(client, clock):
    client.gateway.client.ir_supported = False
    r = client.put(IR, json={"protocol": "NEC"}, headers=H)
    assert (r.status_code, code(r)) == (422, "PROTOCOL_NOT_SUPPORTED")


def test_old_firmware_times_out(client, clock):
    client.gateway.client.node = "silent"
    r = client.put(IR, json={"protocol": "GREE"}, headers=H)
    assert (r.status_code, code(r)) == (504, "NODE_TIMEOUT")


def test_offline_node_and_bad_names_are_refused(client, clock):
    assert code(client.put(IR, json={"protocol": "DAI KIN"}, headers=H)) == "PROTOCOL_NOT_SUPPORTED"
    client.gateway.handle_status("room01", clock(), "offline")
    assert code(client.put(IR, json={"protocol": "GREE"}, headers=H)) == "NODE_OFFLINE"
    assert code(client.post(IR + "/learn", json={}, headers=H)) == "NODE_OFFLINE"


def test_confirm_records_who_and_resets_on_change(client, clock):
    telemetry(client.gateway, clock)
    r = client.post(IR + "/confirm", json={"works": True}, headers=H)
    assert r.json()["confirmed"] is True and r.json()["confirmed_by"] == "khoa API"
    telemetry(client.gateway, clock, proto="GREE")            # nap lai firmware / doi giao thuc
    assert client.get(IR, headers=H).json()["confirmed"] is False


def test_remote_of_room_protocol_syncs_state(client, clock):
    g = client.gateway
    telemetry(g, clock, proto="COOLIX")
    g.handle_ir_event("room01", clock(), json.dumps(
        {"protocol": "DAIKIN", "ac": True, "power": "on", "mode": "cool", "temp": 22, "fan": "auto"}))
    assert client.get("/api/v1/rooms/room01", headers=H).json()["ac"] is None or \
        client.get("/api/v1/rooms/room01", headers=H).json()["ac"]["temp"] != 22
    g.handle_ir_event("room01", clock(), json.dumps(
        {"protocol": "COOLIX", "ac": True, "power": "on", "mode": "cool", "temp": 23, "fan": "auto"}))
    assert client.get("/api/v1/rooms/room01", headers=H).json()["ac"]["temp"] == 23
