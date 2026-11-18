"""Theo doi trang thai du kien cua dieu hoa (gateway + store), khong can broker."""
import json

import safety
import store
from safety import AcState

IR = {"protocol": "DAIKIN", "power": "on", "mode": "cool", "temp": 25, "fan": "auto"}


def sent(gateway, cmd_id, room, ts, source, **fields):
    gateway.db.execute("INSERT INTO commands(cmd_id, room, ts_sent, source, payload) VALUES (?,?,?,?,?)",
                       (cmd_id, room, ts, source, json.dumps({"cmd_id": cmd_id, **fields})))
    gateway.db.commit()


def test_remote_press_sets_state_and_hold(gateway):
    gateway.handle_ir_event("room01", 100.0, json.dumps(IR))
    ac = store.ac_row(gateway.db, "room01")
    assert (ac["power"], ac["temp"], ac["source"], ac["uncertain"]) == ("on", 25, "remote", False)
    assert ac["last_on_ts"] == 100.0
    assert ac["hold_until"] == 100.0 + gateway.policy.hold_remote_s


def test_remote_off_starts_compressor_timer(gateway):
    gateway.handle_ir_event("room01", 100.0, json.dumps(IR))
    gateway.handle_ir_event("room01", 200.0, json.dumps({**IR, "power": "off"}))
    ac = store.ac_row(gateway.db, "room01")
    assert (ac["last_on_ts"], ac["last_off_ts"]) == (100.0, 200.0)


def test_temp_change_does_not_touch_on_off_timers(gateway):
    gateway.handle_ir_event("room01", 100.0, json.dumps(IR))
    gateway.handle_ir_event("room01", 150.0, json.dumps({**IR, "temp": 23}))
    ac = store.ac_row(gateway.db, "room01")
    assert (ac["temp"], ac["last_on_ts"], ac["last_off_ts"]) == (23, 100.0, None)


def test_first_seen_off_counts_as_just_turned_off(gateway):
    gateway.handle_ir_event("room01", 100.0, json.dumps({**IR, "power": "off"}))
    assert store.ac_row(gateway.db, "room01")["last_off_ts"] == 100.0


def test_malformed_remote_event_marks_uncertain(gateway):
    gateway.handle_ir_event("room01", 100.0, json.dumps(IR))
    gateway.handle_ir_event("room01", 110.0, json.dumps({**IR, "mode": "turbo"}))
    ac = store.ac_row(gateway.db, "room01")
    assert (ac["mode"], ac["uncertain"]) == ("cool", True)


def test_other_protocol_remote_is_ignored(gateway, monkeypatch):
    import settings
    monkeypatch.setattr(settings, "IR_PROTOCOL", "DAIKIN")
    gateway.handle_ir_event("room01", 100.0, json.dumps({**IR, "protocol": "SAMSUNG_AC"}))
    assert store.ac_row(gateway.db, "room01") is None


def test_successful_command_updates_state(gateway):
    sent(gateway, "c1", "room01", 100.0, "app", power="on", mode="cool", temp=24, fan="low")
    gateway.handle_result("room01", 100.5, json.dumps({"cmd_id": "c1", "ok": True}))
    ac = store.ac_row(gateway.db, "room01")
    assert (ac["power"], ac["temp"], ac["fan"], ac["source"]) == ("on", 24, "low", "app")
    assert ac["hold_until"] == 100.5 + gateway.policy.hold_app_s


def test_failed_command_does_not_update_state(gateway):
    sent(gateway, "c1", "room01", 100.0, "app", power="on", mode="cool", temp=24, fan="low")
    gateway.handle_result("room01", 100.5, json.dumps({"cmd_id": "c1", "ok": False, "error": "x"}))
    assert store.ac_row(gateway.db, "room01") is None


def test_duplicate_result_is_applied_once(gateway):
    sent(gateway, "c1", "room01", 100.0, "app", power="off", mode="cool", temp=24, fan="low")
    gateway.handle_result("room01", 101.0, json.dumps({"cmd_id": "c1", "ok": True}))
    gateway.handle_result("room01", 999.0, json.dumps({"cmd_id": "c1", "ok": True}))   # QoS 1 gui lap
    assert store.ac_row(gateway.db, "room01")["last_off_ts"] == 101.0


def test_result_from_wrong_room_is_ignored(gateway):
    sent(gateway, "c1", "room01", 100.0, "app", power="on", mode="cool", temp=24, fan="low")
    gateway.handle_result("room02", 100.5, json.dumps({"cmd_id": "c1", "ok": True}))
    assert store.ac_row(gateway.db, "room01") is None and store.ac_row(gateway.db, "room02") is None


def test_auto_command_does_not_set_hold(gateway):
    gateway.handle_ir_event("room01", 100.0, json.dumps(IR))
    store.clear_hold(gateway.db, "room01")
    sent(gateway, "c1", "room01", 200.0, "ai", power="on", mode="cool", temp=26, fan="auto")
    gateway.handle_result("room01", 200.5, json.dumps({"cmd_id": "c1", "ok": True}))
    ac = store.ac_row(gateway.db, "room01")
    assert (ac["temp"], ac["source"], ac["hold_until"]) == (26, "ai", None)


def test_node_offline_marks_state_uncertain_until_human_acts(gateway):
    gateway.handle_ir_event("room01", 100.0, json.dumps(IR))
    gateway.handle_status("room01", 200.0, "offline")
    gateway.handle_status("room01", 300.0, "online")
    assert store.ac_row(gateway.db, "room01")["uncertain"] is True
    gateway.handle_ir_event("room01", 400.0, json.dumps(IR))
    assert store.ac_row(gateway.db, "room01")["uncertain"] is False


def test_gateway_restart_marks_uncertain_and_keeps_timers(gateway):
    import gateway as gw
    gateway.handle_ir_event("room01", 100.0, json.dumps({**IR, "power": "off"}))
    ac = store.ac_row(gw.Gateway().db, "room01")
    assert (ac["uncertain"], ac["last_off_ts"]) == (True, 100.0)


def test_heal_clock_pulls_future_timestamps_back(gateway):
    p = gateway.policy
    store.apply_state_change(gateway.db, "room01", 5000.0, "remote", AcState("off", "cool", 26, "auto"), p)
    assert store.heal_clock(gateway.db, 1000.0, p) == 1
    ac = store.ac_row(gateway.db, "room01")
    assert (ac["ts"], ac["last_off_ts"], ac["last_on_ts"]) == (1000.0, 1000.0, None)
    assert ac["hold_until"] == 1000.0 + p.hold_remote_s
    assert store.heal_clock(gateway.db, 1000.0, p) == 0


def test_room_view_collects_everything(gateway):
    gateway.handle_status("room01", 50.0, "online")
    gateway.handle_telemetry("room01", 90.0, json.dumps({"temp": 28.0, "hum": 60, "presence": True}))
    gateway.handle_ir_event("room01", 100.0, json.dumps(IR))
    sent(gateway, "c1", "room01", 120.0, "ai", power="on", mode="cool", temp=26, fan="auto")
    sent(gateway, "c2", "room01", 130.0, "app", power="on", mode="cool", temp=24, fan="auto")
    v = store.load_room_view(gateway.db, "room01")
    assert v.node_online and v.ac == AcState("on", "cool", 25, "auto") and not v.uncertain
    assert (v.last_cmd_ts, v.last_auto_ts, v.telemetry_ts, v.presence) == (130.0, 120.0, 90.0, True)


def test_room_view_of_unknown_room_is_conservative(gateway):
    v = store.load_room_view(gateway.db, "nowhere")
    assert v == safety.RoomView(node_online=False)
