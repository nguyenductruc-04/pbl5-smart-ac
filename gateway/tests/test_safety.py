"""Unit test cho tung luat cua Safety Layer (ham thuan, khong can database hay MQTT)."""
from dataclasses import replace

import pytest

import safety as s
from safety import AcState, Policy, RoomView, evaluate, resolve_target

P = Policy()
NOW = 10_000.0
ON26 = AcState("on", "cool", 26, "auto")
OFF = AcState("off", "cool", 26, "auto")


def room(**kw):
    """Phong "ly tuong": node online, dieu hoa dang bat 26 do, moi thu da on dinh tu lau."""
    base = dict(node_online=True, ac=ON26, uncertain=False, last_on_ts=NOW - 5000,
                last_off_ts=NOW - 6000, last_cmd_ts=NOW - 5000, last_auto_ts=None,
                hold_until=None, telemetry_ts=NOW - 10, presence=True)
    base.update(kw)
    return RoomView(**base)


# ------------------------------------------------------------------ resolve_target
def test_resolve_keeps_unspecified_fields():
    assert resolve_target(ON26, P, temp=24) == AcState("on", "cool", 24, "auto")


def test_resolve_unknown_state_uses_defaults():
    assert resolve_target(None, P, power="on") == AcState("on", P.default_mode, P.default_temp, P.default_fan)


# ------------------------------------------------------------------ chung
def test_unknown_source_raises():
    with pytest.raises(ValueError):
        evaluate("hacker", ON26, room(), NOW, P)


@pytest.mark.parametrize("source", ["app", "cli", "rule", "ai"])
def test_node_offline_rejects_everything(source):
    d = evaluate(source, OFF, room(node_online=False), NOW, P)
    assert (d.verdict, d.code) == (s.REJECT, s.NODE_OFFLINE)


# ------------------------------------------------------------------ thu cong
def test_manual_change_is_allowed():
    assert evaluate("app", replace(ON26, temp=22), room(), NOW, P).allowed


def test_manual_allowed_even_when_state_uncertain_or_unknown():
    assert evaluate("app", ON26, room(ac=None, uncertain=True, last_off_ts=None), NOW, P).allowed


def test_manual_resend_same_state_is_allowed():
    """IR mot chieu: nguoi dung duoc gui lai de dong bo khi dieu hoa lo mat tin hieu."""
    assert evaluate("app", ON26, room(), NOW, P).allowed


@pytest.mark.parametrize("temp", [15, 31])
def test_manual_temp_out_of_range(temp):
    assert evaluate("app", replace(ON26, temp=temp), room(), NOW, P).code == s.TEMP_OUT_OF_RANGE


@pytest.mark.parametrize("temp", [16, 30])
def test_manual_temp_bounds_inclusive(temp):
    assert evaluate("app", replace(ON26, temp=temp), room(), NOW, P).allowed


def test_manual_rate_limit_with_retry_after():
    d = evaluate("app", replace(ON26, temp=25), room(last_cmd_ts=NOW - 0.5), NOW, P)
    assert (d.code, d.retry_after_s) == (s.RATE_LIMIT, 2)
    assert evaluate("app", replace(ON26, temp=25), room(last_cmd_ts=NOW - 2), NOW, P).allowed


def test_human_can_always_turn_off():
    """Tat khong bi gioi han tan suat, ke ca ngay sau lenh truoc."""
    assert evaluate("app", OFF, room(last_cmd_ts=NOW), NOW, P).allowed


def test_manual_is_not_blocked_by_hold_or_stale_telemetry():
    r = room(hold_until=NOW + 999, telemetry_ts=None, presence=False)
    assert evaluate("app", replace(ON26, temp=24), r, NOW, P).allowed


# ------------------------------------------------------------------ may nen
@pytest.mark.parametrize("source", ["app", "rule"])
def test_compressor_min_off_blocks_restart(source):
    r = room(ac=OFF, last_off_ts=NOW - 60)
    d = evaluate(source, ON26, r, NOW, P)
    assert (d.code, d.retry_after_s) == (s.COMPRESSOR_MIN_OFF, 120)


def test_compressor_reason_wins_over_rate_limit():
    r = room(ac=OFF, last_off_ts=NOW - 1, last_cmd_ts=NOW - 1)
    assert evaluate("app", ON26, r, NOW, P).code == s.COMPRESSOR_MIN_OFF


def test_confirmed_manual_early_start_is_allowed_and_labelled():
    r = room(ac=OFF, last_off_ts=NOW - 60, last_cmd_ts=NOW - 60)
    d = evaluate("app", ON26, r, NOW, P, confirmed=True)
    assert (d.verdict, d.code) == (s.ALLOW, s.EARLY_START_CONFIRMED)


def test_confirmation_does_not_bypass_rate_limit():
    r = room(ac=OFF, last_off_ts=NOW - 1, last_cmd_ts=NOW - 1)
    assert evaluate("app", ON26, r, NOW, P, confirmed=True).code == s.RATE_LIMIT


@pytest.mark.parametrize("source", ["rule", "ai"])
def test_confirmation_is_ignored_for_automatic_commands(source):
    r = room(ac=OFF, last_off_ts=NOW - 60, hold_until=None, last_auto_ts=None)
    assert evaluate(source, ON26, r, NOW, P, confirmed=True).code == s.COMPRESSOR_MIN_OFF


def test_compressor_min_off_boundary():
    assert evaluate("app", ON26, room(ac=OFF, last_off_ts=NOW - P.min_off_s), NOW, P).allowed


def test_fan_mode_is_exempt_from_compressor_rule():
    target = AcState("on", "fan", 26, "low")
    assert evaluate("app", target, room(ac=OFF, last_off_ts=NOW - 5), NOW, P).allowed


def test_clock_going_backwards_is_fail_safe():
    """Moc "tat" nam o tuong lai (dong ho bi lui) -> coi nhu vua tat, van chan."""
    d = evaluate("app", ON26, room(ac=OFF, last_off_ts=NOW + 500), NOW, P)
    assert (d.code, d.retry_after_s) == (s.COMPRESSOR_MIN_OFF, 180)


def test_auto_cannot_stop_compressor_too_soon_but_human_can():
    r = room(last_on_ts=NOW - 60)
    d = evaluate("ai", OFF, r, NOW, P)
    assert (d.code, d.retry_after_s) == (s.COMPRESSOR_MIN_ON, 240)
    assert evaluate("app", OFF, r, NOW, P).allowed


# ------------------------------------------------------------------ tu dong
def test_auto_small_step_allowed():
    assert evaluate("ai", replace(ON26, temp=27), room(), NOW, P).allowed


def test_auto_blocked_when_state_uncertain():
    assert evaluate("ai", replace(ON26, temp=27), room(uncertain=True), NOW, P).code == s.STATE_UNCERTAIN
    assert evaluate("rule", ON26, room(ac=None), NOW, P).code == s.STATE_UNCERTAIN


def test_auto_blocked_during_manual_hold():
    d = evaluate("ai", replace(ON26, temp=27), room(hold_until=NOW + 90), NOW, P)
    assert (d.code, d.retry_after_s) == (s.MANUAL_HOLD, 90)
    assert evaluate("ai", replace(ON26, temp=27), room(hold_until=NOW), NOW, P).allowed


def test_auto_no_change_is_skipped_not_sent():
    d = evaluate("rule", ON26, room(), NOW, P)
    assert (d.verdict, d.code) == (s.SKIP, s.NO_CHANGE)


@pytest.mark.parametrize("telemetry_ts", [None, NOW - 121])
def test_auto_needs_fresh_telemetry(telemetry_ts):
    d = evaluate("ai", replace(ON26, temp=27), room(telemetry_ts=telemetry_ts), NOW, P)
    assert d.code == s.TELEMETRY_STALE


def test_auto_never_turns_on_in_empty_room():
    r = room(ac=OFF, presence=False)
    assert evaluate("rule", ON26, r, NOW, P).code == s.ROOM_EMPTY
    assert evaluate("rule", ON26, replace(r, presence=None), NOW, P).allowed   # chua co cam bien
    assert evaluate("rule", ON26, replace(r, presence=True), NOW, P).allowed


def test_auto_may_turn_off_empty_room():
    assert evaluate("rule", OFF, room(presence=False), NOW, P).allowed


@pytest.mark.parametrize("temp", [23, 30])
def test_auto_temp_window_is_narrower(temp):
    r = room(ac=replace(ON26, temp=temp + (1 if temp == 23 else -1)))
    assert evaluate("ai", replace(ON26, temp=temp), r, NOW, P).code == s.TEMP_OUT_OF_RANGE


def test_auto_step_limit():
    assert evaluate("ai", replace(ON26, temp=28), room(), NOW, P).code == s.STEP_TOO_LARGE


def test_auto_rate_limit():
    d = evaluate("ai", replace(ON26, temp=27), room(last_auto_ts=NOW - 100), NOW, P)
    assert (d.code, d.retry_after_s) == (s.RATE_LIMIT, 500)


def test_policy_hold_durations():
    assert P.hold_for("remote") == P.hold_remote_s
    assert P.hold_for("app") == P.hold_for("cli") == P.hold_app_s
    assert P.hold_for("ai") == P.hold_for("rule") == 0
