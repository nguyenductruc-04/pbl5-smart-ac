"""Thiet lap lan dau bang ma tren tem, dang ky / duyet, dang nhap, quyen theo vai tro (v0.10.0)."""
import json

import pytest
from fastapi.testclient import TestClient

import api
import control

KEY = "app-key-0123456789abcdef"
AUTO_KEY = "auto-key-0123456789abcdef"
SETUP_CODE = "ABCD-EFGH-JKMN"
H = {"X-API-Key": KEY}
CMD = "/api/v1/rooms/room01/commands"
VOTE = "/api/v1/rooms/room01/comfort"
PW = "mat-khau-dai-1"


@pytest.fixture
def client(gateway, clock):
    gateway.handle_status("room01", clock(), "online")
    service = control.CommandService(gateway, clock=clock, timeout_s=0.05)
    app = api.create_app(gateway, service, api_key=KEY, automation_key=AUTO_KEY, clock=clock,
                         setup_code=SETUP_CODE, device_id="d3v1ce00")
    with TestClient(app) as c:
        c.gateway = gateway
        yield c


def code(resp):
    return resp.json()["error"]["code"]


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def claim(client, username="truc"):
    r = client.post("/api/v1/setup", json={"code": SETUP_CODE, "username": username, "password": PW})
    assert r.status_code == 201, r.text
    return bearer(r.json()["token"])


def user(client, admin, username, role):
    """Tu dang ky roi quan tri vien cap quyen; tra ve header dang nhap cua nguoi do."""
    assert client.post("/api/v1/auth/register", json={"username": username, "password": PW}).status_code == 201
    assert client.put(f"/api/v1/users/{username}", json={"role": role}, headers=admin).status_code == 200
    r = client.post("/api/v1/auth/login", json={"username": username, "password": PW})
    assert r.status_code == 200, r.text
    return bearer(r.json()["token"])


def telemetry(client, clock):
    client.gateway.handle_telemetry("room01", clock(), json.dumps({"temp": 28.5, "hum": 60, "presence": True}))


# ------------------------------------------------------------------ thiet lap lan dau
def test_new_pi_reports_unclaimed_without_login(client):
    assert client.get("/api/v1/setup/status").json() == {"claimed": False, "device_id": "d3v1ce00",
                                                         "version": api.__version__}


def test_setup_needs_the_code_on_the_label(client):
    r = client.post("/api/v1/setup", json={"code": "AAAA-AAAA-AAAA", "username": "truc", "password": PW})
    assert (r.status_code, code(r)) == (403, "SETUP_CODE_INVALID")
    r = client.post("/api/v1/setup", json={"code": "abcd efgh jkmn", "username": "Truc", "password": PW})
    assert r.status_code == 201
    assert r.json()["user"] == r.json()["user"] | {"username": "truc", "role": "admin"}
    me = client.get("/api/v1/auth/me", headers=bearer(r.json()["token"])).json()
    assert (me["username"], me["role"], me["kind"]) == ("truc", "admin", "user")
    assert client.get("/api/v1/setup/status").json()["claimed"] is True


def test_setup_works_only_once(client):
    claim(client)
    r = client.post("/api/v1/setup", json={"code": SETUP_CODE, "username": "ke-gian", "password": PW})
    assert (r.status_code, code(r)) == (409, "ALREADY_CLAIMED")


def test_guessing_the_setup_code_is_rate_limited(client):
    for _ in range(5):
        client.post("/api/v1/setup", json={"code": "AAAA-AAAA-AAAA", "username": "truc", "password": PW})
    r = client.post("/api/v1/setup", json={"code": SETUP_CODE, "username": "truc", "password": PW})
    assert (r.status_code, code(r)) == (429, "SETUP_TOO_MANY")


# ------------------------------------------------------------------ dang ky, duyet, dang nhap
def test_register_before_setup_is_refused(client):
    r = client.post("/api/v1/auth/register", json={"username": "lan", "password": PW})
    assert (r.status_code, code(r)) == (409, "NOT_CLAIMED")


def test_registered_user_waits_for_approval(client):
    admin = claim(client)
    r = client.post("/api/v1/auth/register", json={"username": "lan", "password": PW})
    assert (r.status_code, r.json()["status"]) == (201, "pending")
    r = client.post("/api/v1/auth/login", json={"username": "lan", "password": PW})
    assert (r.status_code, code(r)) == (403, "ACCOUNT_PENDING")
    users = client.get("/api/v1/users", headers=admin).json()["items"]
    assert [(u["username"], u["role"]) for u in users] == [("lan", "pending"), ("truc", "admin")]
    r = client.put("/api/v1/users/lan", json={"role": "member"}, headers=admin)
    assert (r.json()["role"], r.json()["approved_by"]) == ("member", "truc")
    assert client.post("/api/v1/auth/login", json={"username": "lan", "password": PW}).status_code == 200


def test_duplicate_username_is_a_conflict(client):
    claim(client)
    r = client.post("/api/v1/auth/register", json={"username": "TRUC", "password": PW})
    assert (r.status_code, code(r)) == (409, "USERNAME_TAKEN")


def test_wrong_password_locks_the_name_for_a_while(client, clock):
    claim(client)
    for _ in range(api.LOGIN_MAX_FAILS):
        r = client.post("/api/v1/auth/login", json={"username": "truc", "password": "sai-mat-khau"})
        assert (r.status_code, code(r)) == (401, "LOGIN_FAILED")
    r = client.post("/api/v1/auth/login", json={"username": "truc", "password": PW})
    assert (r.status_code, code(r)) == (429, "LOGIN_LOCKED")
    clock.advance(api.LOGIN_WINDOW_S + 1)
    assert client.post("/api/v1/auth/login", json={"username": "truc", "password": PW}).status_code == 200


def test_logout_revokes_the_session(client):
    admin = claim(client)
    assert client.post("/api/v1/auth/logout", headers=admin).status_code == 204
    r = client.get("/api/v1/rooms", headers=admin)
    assert (r.status_code, code(r)) == (401, "SESSION_INVALID")


def test_change_password_needs_the_old_one(client):
    admin = claim(client)
    r = client.put("/api/v1/auth/password", json={"old_password": "sai", "new_password": "mat-khau-moi"},
                   headers=admin)
    assert (r.status_code, code(r)) == (403, "WRONG_PASSWORD")
    r = client.put("/api/v1/auth/password", json={"old_password": PW, "new_password": "mat-khau-moi"},
                   headers=admin)
    assert r.status_code == 200
    assert client.get("/api/v1/rooms", headers=admin).status_code == 200       # thiet bi nay van dang nhap
    assert client.post("/api/v1/auth/login", json={"username": "truc", "password": "mat-khau-moi"}).status_code == 200


# ------------------------------------------------------------------ quyen theo vai tro
def test_member_controls_but_does_not_administer(client):
    member = user(client, claim(client), "lan", "member")
    assert client.post(CMD, json={"power": "on", "temp": 25}, headers=member).json()["status"] != "rejected"
    for method, path, body in [("get", "/api/v1/users", None), ("put", "/api/v1/users/lan", {"role": "admin"}),
                               ("put", "/api/v1/system/network", {"mode": "auto"})]:
        r = getattr(client, method)(path, headers=member, **({"json": body} if body else {}))
        assert (r.status_code, code(r)) == (403, "FORBIDDEN"), path


def test_guest_only_looks(client, clock):
    guest = user(client, claim(client), "khach", "guest")
    assert client.get("/api/v1/rooms/room01", headers=guest).status_code == 200
    telemetry(client, clock)
    for path, body in [(CMD, {"power": "on"}), (VOTE, {"vote": "cooler"}), ("/api/v1/pairing", None),
                       (CMD + "/resend", None)]:
        r = client.post(path, headers=guest, **({"json": body} if body else {}))
        assert (r.status_code, code(r)) == (403, "FORBIDDEN"), path
    assert client.delete("/api/v1/rooms/room01/auto-hold", headers=guest).status_code == 403
    assert client.gateway.client.published == []


def test_role_change_applies_at_once(client):
    admin = claim(client)
    lan = user(client, admin, "lan", "member")
    client.put("/api/v1/users/lan", json={"role": "guest"}, headers=admin)
    assert client.post(CMD, json={"power": "on"}, headers=lan).status_code == 403
    client.delete("/api/v1/users/lan", headers=admin)
    assert code(client.get("/api/v1/rooms", headers=lan)) == "SESSION_INVALID"


def test_last_admin_cannot_step_down(client):
    admin = claim(client)
    r = client.put("/api/v1/users/truc", json={"role": "member"}, headers=admin)
    assert (r.status_code, code(r)) == (409, "LAST_ADMIN")
    assert client.put("/api/v1/users/khong-co", json={"role": "guest"}, headers=admin).status_code == 404


def test_app_key_still_works_as_an_admin_tool(client):
    claim(client)
    assert client.get("/api/v1/users", headers=H).status_code == 200
    assert client.get("/api/v1/auth/me", headers=H).json()["kind"] == "key"


def test_votes_remember_who_sent_them(client, clock):
    admin = claim(client)
    lan = user(client, admin, "lan", "member")
    nam = user(client, admin, "nam", "member")
    telemetry(client, clock)
    v = client.post(VOTE, json={"vote": "cooler"}, headers=lan).json()
    assert (v["user_id"] is not None, v["username"]) == (True, "lan")
    r = client.delete(f"{VOTE}/{v['id']}", headers=nam)
    assert (r.status_code, code(r)) == (403, "NOT_YOUR_VOTE")
    assert client.delete(f"{VOTE}/{v['id']}", headers=lan).status_code == 200


def test_pairing_logs_in_as_the_person_who_made_the_code(client):
    lan = user(client, claim(client), "lan", "member")
    c = client.post("/api/v1/pairing", headers=lan).json()["code"]
    r = client.post("/api/v1/pairing/claim", json={"code": c})
    assert "api_key" not in r.json()
    me = client.get("/api/v1/auth/me", headers=bearer(r.json()["token"])).json()
    assert (me["username"], me["role"]) == ("lan", "member")
