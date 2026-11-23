"""Tai khoan: bam mat khau, vai tro, phien dang nhap, ma thiet lap (khong qua HTTP)."""
import sqlite3

import pytest

import accounts
import store

T0 = 1_000_000.0


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    store.init(conn)
    yield conn
    conn.close()


def test_password_hash_is_salted_and_verifies():
    a, b = accounts.hash_password("mat-khau-1"), accounts.hash_password("mat-khau-1")
    assert a != b and a.startswith("scrypt$")
    assert accounts.verify_password("mat-khau-1", a)
    assert not accounts.verify_password("mat-khau-2", a)
    assert not accounts.verify_password("x", "rac")          # chuoi hong khong lam vo ham


@pytest.mark.parametrize("name", ["ab", "-abc", "co dau cach", "a" * 33, "tên"])
def test_bad_usernames_are_rejected(db, name):
    with pytest.raises(accounts.AccountError) as e:
        accounts.create_user(db, name, "mat-khau-dai", accounts.MEMBER, T0)
    assert e.value.code == "BAD_USERNAME"


def test_usernames_are_case_insensitive_and_unique(db):
    accounts.create_user(db, "Truc", "mat-khau-dai", accounts.ADMIN, T0)
    with pytest.raises(accounts.AccountError) as e:
        accounts.create_user(db, "truc", "mat-khau-khac", accounts.MEMBER, T0)
    assert e.value.code == "USERNAME_TAKEN"
    assert accounts.authenticate(db, "TRUC", "mat-khau-dai")["username"] == "truc"


@pytest.mark.parametrize("pw", ["ngan", "truc0404"])
def test_weak_passwords_are_rejected(db, pw):
    with pytest.raises(accounts.AccountError) as e:
        accounts.create_user(db, "truc0404", pw, accounts.MEMBER, T0)
    assert e.value.code == "BAD_PASSWORD"


def test_authenticate_unknown_user_returns_none(db):
    assert accounts.authenticate(db, "khong-co", "mat-khau-dai") is None


def test_last_admin_cannot_be_demoted_or_deleted(db):
    accounts.create_user(db, "truc", "mat-khau-dai", accounts.ADMIN, T0)
    for fn in (lambda: accounts.set_role(db, "truc", accounts.MEMBER, "truc", T0),
               lambda: accounts.delete_user(db, "truc")):
        with pytest.raises(accounts.AccountError) as e:
            fn()
        assert e.value.code == "LAST_ADMIN"
    accounts.create_user(db, "nam", "mat-khau-dai", accounts.PENDING, T0)
    accounts.set_role(db, "nam", accounts.ADMIN, "truc", T0 + 1)
    assert accounts.set_role(db, "truc", accounts.MEMBER, "nam", T0 + 2)["role"] == accounts.MEMBER


def test_approval_records_who_and_when(db):
    accounts.create_user(db, "truc", "mat-khau-dai", accounts.ADMIN, T0)
    accounts.create_user(db, "lan", "mat-khau-dai", accounts.PENDING, T0)
    assert accounts.list_users(db)[0]["username"] == "lan"      # cho duyet len dau
    u = accounts.set_role(db, "lan", accounts.GUEST, "truc", T0 + 5)
    assert (u["role"], u["approved_by"], u["approved_ts"]) == ("guest", "truc", T0 + 5)


def test_sessions_slide_and_expire(db):
    u = accounts.create_user(db, "truc", "mat-khau-dai", accounts.ADMIN, T0)
    tok = accounts.new_session(db, u["id"], T0, "Pixel")
    assert accounts.session_user(db, tok, T0 + 10)["username"] == "truc"
    # dung deu dan thi khong bao gio het han
    t = T0
    for _ in range(5):
        t += accounts.SESSION_TTL_S - 100
        assert accounts.session_user(db, tok, t) is not None
    # bo khong dung qua TTL thi het
    assert accounts.session_user(db, tok, t + accounts.SESSION_TTL_S + 1) is None
    assert accounts.session_user(db, "rac", T0) is None


def test_only_the_token_hash_is_stored(db):
    u = accounts.create_user(db, "truc", "mat-khau-dai", accounts.ADMIN, T0)
    tok = accounts.new_session(db, u["id"], T0)
    stored = [r[0] for r in db.execute("SELECT token_hash FROM sessions")]
    assert stored and tok not in stored


def test_password_change_logs_out_other_devices(db):
    u = accounts.create_user(db, "truc", "mat-khau-dai", accounts.ADMIN, T0)
    keep, other = accounts.new_session(db, u["id"], T0), accounts.new_session(db, u["id"], T0)
    accounts.change_password(db, u["id"], "mat-khau-moi", keep)
    assert accounts.session_user(db, keep, T0 + 1) is not None
    assert accounts.session_user(db, other, T0 + 1) is None
    assert accounts.authenticate(db, "truc", "mat-khau-moi") is not None


def test_deleting_or_demoting_to_pending_kills_sessions(db):
    accounts.create_user(db, "truc", "mat-khau-dai", accounts.ADMIN, T0)
    u = accounts.create_user(db, "lan", "mat-khau-dai", accounts.MEMBER, T0)
    tok = accounts.new_session(db, u["id"], T0)
    accounts.delete_user(db, "lan")
    assert accounts.session_user(db, tok, T0 + 1) is None


def test_reset_removes_accounts_but_keeps_data(db):
    u = accounts.create_user(db, "truc", "mat-khau-dai", accounts.ADMIN, T0)
    accounts.new_session(db, u["id"], T0)
    db.execute("INSERT INTO comfort_votes(ts, room, vote, user_id, username) VALUES (?,?,?,?,?)",
               (T0, "room01", "ok", u["id"], "truc"))
    assert accounts.reset_accounts(db) == 1
    assert not accounts.has_admin(db)
    assert db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM comfort_votes").fetchone()[0] == 1


def test_setup_code_is_created_once_private_and_readable(tmp_path):
    p = tmp_path / "setup_code"
    code = accounts.setup_code(p)
    assert code == accounts.setup_code(p) and len(code) == 14 and code.count("-") == 2
    assert set(code.replace("-", "")) <= set(accounts.CODE_ALPHABET)
    assert p.stat().st_mode & 0o777 == 0o600
    assert accounts.setup_code_matches(code.lower().replace("-", " "), code)
    assert not accounts.setup_code_matches("AAAA-AAAA-AAAA", code)
    dev = accounts.device_id(tmp_path / "device_id")
    assert accounts.setup_uri(code, dev) == f"pbl5://setup?id={dev}&code={code}"


def test_old_database_gets_vote_user_columns(tmp_path):
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE comfort_votes(id INTEGER PRIMARY KEY, ts REAL, room TEXT, vote TEXT)")
    conn.execute("INSERT INTO comfort_votes(ts, room, vote) VALUES (1, 'room01', 'ok')")
    conn.commit()
    store.init(conn)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(comfort_votes)")}
    assert {"user_id", "username"} <= cols
    assert conn.execute("SELECT vote FROM comfort_votes").fetchone() == ("ok",)
