"""Unit tests cho logic watchdog Wi-Fi (khong goi nmcli that)."""
import pytest

import netmode
import netwatch as nw
from netwatch import AP, HOME, NONE, OFFLINE, START_AP, STOP_AP, Memory, decide, parse_state


def test_home_never_acts():
    mem = Memory()
    for t in range(0, 1000, 15):
        assert decide(HOME, t, mem) == NONE


def test_short_outage_does_not_start_ap():
    mem = Memory()
    assert decide(OFFLINE, 0, mem) == NONE
    assert decide(OFFLINE, nw.OFFLINE_BEFORE_AP_S - 1, mem) == NONE
    assert decide(HOME, nw.OFFLINE_BEFORE_AP_S, mem) == NONE      # mang tro lai kip
    assert decide(OFFLINE, nw.OFFLINE_BEFORE_AP_S + 10, mem) == NONE  # bo dem bat dau lai


def test_long_outage_starts_ap():
    mem = Memory()
    decide(OFFLINE, 0, mem)
    assert decide(OFFLINE, nw.OFFLINE_BEFORE_AP_S, mem) == START_AP


def test_ap_retries_home_periodically():
    mem = Memory()
    decide(OFFLINE, 0, mem)
    decide(OFFLINE, nw.OFFLINE_BEFORE_AP_S, mem)            # START_AP
    t0 = nw.OFFLINE_BEFORE_AP_S
    assert decide(AP, t0 + 15, mem) == NONE
    assert decide(AP, t0 + nw.RETRY_HOME_EVERY_S, mem) == STOP_AP


def test_failed_home_retry_restarts_ap_after_window():
    mem = Memory()
    mem.last_home_try = 0
    assert decide(AP, nw.RETRY_HOME_EVERY_S, mem) == STOP_AP
    t = nw.RETRY_HOME_EVERY_S
    assert decide(OFFLINE, t + 10, mem) == NONE                       # dang cho Wi-Fi nha
    assert decide(OFFLINE, t + nw.RETRY_WINDOW_S, mem) == START_AP    # het cua so -> bat lai AP


def test_successful_home_retry_stays_home():
    mem = Memory()
    mem.last_home_try = 0
    decide(AP, nw.RETRY_HOME_EVERY_S, mem)                    # STOP_AP
    assert decide(HOME, nw.RETRY_HOME_EVERY_S + 20, mem) == NONE
    assert decide(HOME, nw.RETRY_HOME_EVERY_S + 2000, mem) == NONE


def test_parse_state():
    out = "wlan0:connected:Mai\neth0:unavailable:\nlo:connected (externally):lo\n"
    assert parse_state(out) == HOME
    assert parse_state("wlan0:connected:SmartAC-Backup\n") == AP
    assert parse_state("wlan0:disconnected:\n") == OFFLINE
    assert parse_state("wlan0:connecting (getting IP configuration):Mai\n") == OFFLINE
    assert parse_state("eth0:connected:Wired\n") == OFFLINE  # khong co wlan0


def test_parse_state_connection_name_with_colon_like_text():
    assert parse_state("wlan0:connected:netplan-wlan0-Xiaomi 13T\n") == HOME


def test_home_connections_filters_and_sorts():
    out = (
        "lo:loopback:no:0\n"
        "SmartAC-Backup:802-11-wireless:no:0\n"
        "Mai:802-11-wireless:yes:20\n"
        "xiaomi:802-11-wireless:yes:10\n"
        "old-hotspot:802-11-wireless:no:0\n"
        "netplan-wlan0-Xiaomi 13T:802-11-wireless:yes:0\n"
        "Wired:802-3-ethernet:yes:0\n"
    )
    assert nw.home_connections(out) == ["Mai", "xiaomi", "netplan-wlan0-Xiaomi 13T"]


def test_home_connections_name_with_escaped_colon():
    assert nw.home_connections("Cafe\\:Wifi:802-11-wireless:yes:0\n") == ["Cafe:Wifi"]


def test_home_connections_never_returns_ap():
    assert nw.home_connections("SmartAC-Backup:802-11-wireless:yes:99\n") == []


# ------------------------------------------------------------------ che do mang (v0.10.0)
def test_standalone_starts_ap_immediately_and_stays():
    mem = Memory()
    assert decide(HOME, 0, mem, nw.STANDALONE) == START_AP          # ke ca dang co Wi-Fi nha
    assert decide(OFFLINE, 1, mem, nw.STANDALONE) == START_AP
    for t in range(0, 5 * nw.RETRY_HOME_EVERY_S, 15):
        assert decide(AP, t, mem, nw.STANDALONE) == NONE              # khong bao gio thu ve nha


def test_home_only_never_starts_ap_and_leaves_it():
    mem = Memory()
    for t in range(0, 3 * nw.OFFLINE_BEFORE_AP_S, 15):
        assert decide(OFFLINE, t, mem, nw.HOME_ONLY) == NONE
    assert decide(AP, 0, mem, nw.HOME_ONLY) == STOP_AP


def test_network_mode_reads_env_and_falls_back_to_auto(monkeypatch, tmp_path):
    monkeypatch.setattr(netmode, "MODE_FILE", tmp_path / "network_mode")
    monkeypatch.setenv("NETWORK_MODE", "Standalone")
    assert nw.network_mode() == nw.STANDALONE
    monkeypatch.setenv("NETWORK_MODE", "bogus")
    assert nw.network_mode() == nw.AUTO


def test_dashboard_choice_overrides_env_until_removed(monkeypatch, tmp_path):
    f = tmp_path / "network_mode"
    monkeypatch.setenv("NETWORK_MODE", "auto")
    netmode.choose_mode("home", f)
    assert netmode.effective_mode(f) == nw.HOME_ONLY
    f.write_text("garbage")                                   # file hong -> ve mac dinh
    assert netmode.effective_mode(f) == nw.AUTO
    f.unlink()
    assert netmode.effective_mode(f) == nw.AUTO
    with pytest.raises(ValueError):
        netmode.choose_mode("party", f)


def test_status_file_round_trip_and_staleness(tmp_path):
    f = tmp_path / "status.json"
    assert netmode.read_status(100.0, f) is None
    netmode.write_status({"mode": "auto", "state": "home", "ts": 100.0}, f)
    assert netmode.read_status(130.0, f)["running"] is True
    assert netmode.read_status(100.0 + netmode.STATUS_STALE_S + 1, f)["running"] is False


def test_connection_name():
    out = "wlan0:connected:Nha Mai\neth0:unavailable:\n"
    assert nw.connection_name(out) == "Nha Mai"
    assert nw.connection_name("wlan0:disconnected:\n") == ""


def test_switching_back_to_auto_on_ap_retries_home_at_once():
    mem = nw.fresh_memory(1000.0)
    assert decide(AP, 1000.0, mem, nw.AUTO) == STOP_AP
    assert decide(HOME, 1030.0, mem, nw.AUTO) == NONE
