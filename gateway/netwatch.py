"""
Wi-Fi watchdog cho Raspberry Pi (xem docs/adr/0001-node-wifi-provisioning.md).

- Pi mat Wi-Fi nha lien tuc OFFLINE_BEFORE_AP_S giay -> bat AP du phong (SmartAC-Backup, 10.42.0.1).
- Dang o che do AP: cu RETRY_HOME_EVERY_S giay tat AP va CHU DONG bat lan luot cac mang Wi-Fi nha
  da luu (autoconnect=yes, uu tien cao truoc). Ket noi duoc thi o lai, khong thi bat lai AP.
  Khong cho NetworkManager tu ket noi, vi NM co the da chan tu ket noi (that bai nhieu lan,
  hoac nguoi dung vua "connection down") -> Pi se ket o che do AP mai mai.

Logic quyet dinh nam trong ham thuan `decide()` (khong goi he thong) de unit test duoc.
Chay nhu dich vu systemd: xem gateway/pbl5-netwatch.service
"""
import logging
import subprocess
import time
from dataclasses import dataclass

AP_CONNECTION = "SmartAC-Backup"
WIFI_DEVICE = "wlan0"
CHECK_INTERVAL_S = 15
OFFLINE_BEFORE_AP_S = 120   # mat mang bao lau thi bat AP
RETRY_HOME_EVERY_S = 300    # dang o AP, bao lau thu quay ve Wi-Fi nha mot lan
RETRY_WINDOW_S = 45         # thoi gian toi da cho mot lan thu quay ve Wi-Fi nha
CONNECT_WAIT_S = 20         # cho moi mang Wi-Fi nha toi da bao lau

log = logging.getLogger("netwatch")

# Trang thai Wi-Fi quan sat duoc
HOME, AP, OFFLINE = "home", "ap", "offline"
# Hanh dong
NONE, START_AP, STOP_AP = "none", "start_ap", "stop_ap"


@dataclass
class Memory:
    offline_since: float | None = None   # bat dau mat mang tu luc nao
    last_home_try: float | None = None   # lan cuoi tat AP de thu Wi-Fi nha
    trying_until: float | None = None    # dang trong cua so thu Wi-Fi nha


def decide(state: str, now: float, mem: Memory) -> str:
    """Tra ve hanh dong can lam. Cap nhat `mem` tai cho."""
    if state == HOME:
        mem.offline_since = None
        mem.trying_until = None
        return NONE

    if state == AP:
        mem.offline_since = None
        mem.trying_until = None
        if mem.last_home_try is None:
            mem.last_home_try = now
        if now - mem.last_home_try >= RETRY_HOME_EVERY_S:
            mem.last_home_try = now
            mem.trying_until = now + RETRY_WINDOW_S
            return STOP_AP
        return NONE

    # OFFLINE
    if mem.trying_until is not None:
        if now < mem.trying_until:
            return NONE                      # dang cho Wi-Fi nha tu ket noi
        mem.trying_until = None              # thu that bai -> quay lai AP
        mem.offline_since = None
        return START_AP

    if mem.offline_since is None:
        mem.offline_since = now
    if now - mem.offline_since >= OFFLINE_BEFORE_AP_S:
        mem.offline_since = None
        mem.last_home_try = now
        return START_AP
    return NONE


def parse_state(nmcli_output: str, device: str = WIFI_DEVICE, ap_name: str = AP_CONNECTION) -> str:
    """Doc ket qua `nmcli -t -f DEVICE,STATE,CONNECTION device`."""
    for line in nmcli_output.splitlines():
        parts = line.split(":", 2)
        if len(parts) == 3 and parts[0] == device:
            _, dev_state, connection = parts
            if dev_state != "connected":
                return OFFLINE
            return AP if connection == ap_name else HOME
    return OFFLINE


def home_connections(nmcli_output: str, ap_name: str = AP_CONNECTION) -> list[str]:
    """Doc `nmcli -t -f NAME,TYPE,AUTOCONNECT,AUTOCONNECT-PRIORITY connection show`.

    Tra ve cac mang Wi-Fi nha (autoconnect=yes, khong phai AP), uu tien cao truoc.
    """
    found = []
    for line in nmcli_output.splitlines():
        # NAME co the chua ':' -> nmcli escape thanh '\:'; tach tu ben phai
        parts = line.rsplit(":", 3)
        if len(parts) != 4:
            continue
        name, ctype, auto, prio = parts
        name = name.replace("\\:", ":")
        if ctype != "802-11-wireless" or auto != "yes" or name == ap_name:
            continue
        try:
            priority = int(prio)
        except ValueError:
            priority = 0
        found.append((priority, name))
    return [name for _, name in sorted(found, key=lambda x: -x[0])]


def nmcli(*args: str) -> str:
    res = subprocess.run(["nmcli", *args], capture_output=True, text=True, timeout=30)
    if res.returncode != 0:
        log.warning("nmcli %s -> %s", " ".join(args), res.stderr.strip())
    return res.stdout


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    mem = Memory()
    last_state = None
    log.info("netwatch bat dau (AP=%s, device=%s)", AP_CONNECTION, WIFI_DEVICE)
    while True:
        state = parse_state(nmcli("-t", "-f", "DEVICE,STATE,CONNECTION", "device"))
        if state != last_state:
            log.info("Trang thai Wi-Fi: %s", state)
            last_state = state
        action = decide(state, time.monotonic(), mem)
        if action == START_AP:
            log.warning("Mat Wi-Fi nha -> bat AP du phong %s", AP_CONNECTION)
            nmcli("connection", "up", AP_CONNECTION)
        elif action == STOP_AP:
            log.info("Tat AP de thu ket noi lai Wi-Fi nha")
            nmcli("connection", "down", AP_CONNECTION)
            homes = home_connections(
                nmcli("-t", "-f", "NAME,TYPE,AUTOCONNECT,AUTOCONNECT-PRIORITY", "connection", "show"))
            for name in homes:
                log.info("Thu ket noi '%s'", name)
                nmcli("--wait", str(CONNECT_WAIT_S), "connection", "up", name)
                if parse_state(nmcli("-t", "-f", "DEVICE,STATE,CONNECTION", "device")) == HOME:
                    log.info("Da ve Wi-Fi nha '%s'", name)
                    break
            else:
                log.info("Khong ket noi duoc Wi-Fi nha nao (%d mang da luu)", len(homes))
        time.sleep(CHECK_INTERVAL_S)


if __name__ == "__main__":
    main()
