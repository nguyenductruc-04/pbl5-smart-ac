"""Unit tests cho logic watchdog Wi-Fi (khong goi nmcli that)."""
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
