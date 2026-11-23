"""
Tai khoan nguoi dung (v0.9.0). Xem docs/adr/0007-user-accounts.md.

- Lan dau: ai co MA THIET LAP (in tren tem dan Pi) thi tao duoc tai khoan QUAN TRI. Sau do ma vo hieu
  cho toi khi giu nut reset tren Pi (reset_button.py) -> chung minh dang dung canh thiet bi.
- Nguoi khac tu dang ky -> trang thai "pending"; quan tri vien cap quyen theo ten dang nhap:
  admin (moi thu), member (dieu khien, ghi phieu), guest (chi xem).
- Mat khau bam bang scrypt (thu vien chuan Python, khong can goi them). Phien dang nhap: ma ngau nhien
  32 byte, database chi luu SHA-256 cua no.

Module nay khong biet gi ve HTTP: REST API (api.py) va nut reset deu goi vao day.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import secrets
import sqlite3
from pathlib import Path

ADMIN, MEMBER, GUEST, PENDING = "admin", "member", "guest", "pending"
ROLES = (ADMIN, MEMBER, GUEST)                 # quyen quan tri vien cap duoc
ALL_ROLES = ROLES + (PENDING,)

SESSION_TTL_S = 90 * 86400                     # phien het han sau 90 ngay KHONG dung
SESSION_TOUCH_S = 3600                         # gia han / ghi lan dung cuoi toi da moi gio mot lan
SCRYPT_N, SCRYPT_R, SCRYPT_P = 2 ** 14, 8, 1   # ~16 MB RAM, ~50 ms tren Pi 5

USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,31}$")
CODE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"   # bo 0/O, 1/I/L: doc tren tem khong nham

_DIR = Path(__file__).resolve().parent
SETUP_CODE_FILE = _DIR / "setup_code"
DEVICE_ID_FILE = _DIR / "device_id"

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,   -- khong tai su dung id (phieu cu giu user_id)
    username     TEXT NOT NULL UNIQUE,
    display_name TEXT,
    pw_hash      TEXT NOT NULL,
    role         TEXT NOT NULL,
    created_ts   REAL NOT NULL,
    approved_ts  REAL,
    approved_by  TEXT
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash   TEXT PRIMARY KEY,
    user_id      INTEGER NOT NULL,
    device       TEXT,
    created_ts   REAL NOT NULL,
    last_seen_ts REAL NOT NULL,
    expires_ts   REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
"""


class AccountError(Exception):
    """Loi nghiep vu: `code` dung lam ma loi cua API."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


def init(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


# ------------------------------------------------------------------ mat khau
def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=32)
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${_b64(salt)}${_b64(dk)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt, dk = stored.split("$")
        if algo != "scrypt":
            return False
        got = hashlib.scrypt(password.encode(), salt=_unb64(salt), n=int(n), r=int(r), p=int(p),
                             dklen=len(_unb64(dk)))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(got, _unb64(dk))


# Bam san mot mat khau gia: dang nhap ten khong ton tai van ton thoi gian nhu ten co that
# (khong lo ten dang nhap nao co trong he thong qua thoi gian tra loi).
_DUMMY_HASH = hash_password(secrets.token_urlsafe(16))


def normalize_username(username: str) -> str:
    return (username or "").strip().lower()


def check_username(username: str) -> str | None:
    if not USERNAME_RE.match(username):
        return "Ten dang nhap 3-32 ky tu: chu thuong, so, dau cham, gach duoi, gach ngang; bat dau bang chu hoac so"
    return None


def check_password(password: str, username: str) -> str | None:
    if not 8 <= len(password) <= 128:
        return "Mat khau 8-128 ky tu"
    if password.lower() == username:
        return "Mat khau khong duoc trung ten dang nhap"
    return None


# ------------------------------------------------------------------ nguoi dung
def _row_to_user(row) -> dict:
    uid, username, display, role, created, approved, approved_by = row
    return {"id": uid, "username": username, "display_name": display or username, "role": role,
            "created_ts": created, "approved_ts": approved, "approved_by": approved_by}


_USER_COLS = "id, username, display_name, role, created_ts, approved_ts, approved_by"


def has_admin(conn: sqlite3.Connection) -> bool:
    return conn.execute("SELECT 1 FROM users WHERE role=? LIMIT 1", (ADMIN,)).fetchone() is not None


def get_user(conn: sqlite3.Connection, username: str) -> dict | None:
    row = conn.execute(f"SELECT {_USER_COLS} FROM users WHERE username=?",
                       (normalize_username(username),)).fetchone()
    return _row_to_user(row) if row else None


def list_users(conn: sqlite3.Connection) -> list[dict]:
    # Cho duyet len dau, roi theo vai tro, roi theo ten
    rows = conn.execute(
        f"SELECT {_USER_COLS} FROM users ORDER BY role='pending' DESC,"
        " CASE role WHEN 'admin' THEN 0 WHEN 'member' THEN 1 ELSE 2 END, username").fetchall()
    return [_row_to_user(r) for r in rows]


def create_user(conn: sqlite3.Connection, username: str, password: str, role: str, ts: float,
                display_name: str | None = None, approved_by: str | None = None) -> dict:
    username = normalize_username(username)
    if err := check_username(username):
        raise AccountError("BAD_USERNAME", err)
    if err := check_password(password, username):
        raise AccountError("BAD_PASSWORD", err)
    if role not in ALL_ROLES:
        raise AccountError("BAD_ROLE", f"Vai tro phai la mot trong {ALL_ROLES}")
    display_name = (display_name or "").strip()[:40] or None
    try:
        conn.execute(
            "INSERT INTO users(username, display_name, pw_hash, role, created_ts, approved_ts, approved_by)"
            " VALUES (?,?,?,?,?,?,?)",
            (username, display_name, hash_password(password), role, ts,
             None if role == PENDING else ts, approved_by))
    except sqlite3.IntegrityError:
        raise AccountError("USERNAME_TAKEN", "Ten dang nhap nay da co nguoi dung") from None
    conn.commit()
    return get_user(conn, username)


def authenticate(conn: sqlite3.Connection, username: str, password: str) -> dict | None:
    """Tra ve nguoi dung neu dung mat khau (ke ca dang cho duyet), nguoc lai None."""
    row = conn.execute("SELECT pw_hash FROM users WHERE username=?",
                       (normalize_username(username),)).fetchone()
    if row is None:
        verify_password(password, _DUMMY_HASH)
        return None
    return get_user(conn, username) if verify_password(password, row[0]) else None


def _admin_count(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM users WHERE role=?", (ADMIN,)).fetchone()[0]


def set_role(conn: sqlite3.Connection, username: str, role: str, by: str, ts: float) -> dict:
    user = get_user(conn, username)
    if user is None:
        raise AccountError("USER_NOT_FOUND", "Khong co tai khoan nay")
    if role not in ROLES:
        raise AccountError("BAD_ROLE", f"Vai tro phai la mot trong {ROLES}")
    if user["role"] == ADMIN and role != ADMIN and _admin_count(conn) == 1:
        raise AccountError("LAST_ADMIN", "Day la quan tri vien cuoi cung; cap quyen quan tri cho nguoi khac truoc")
    approved = user["approved_ts"] or ts
    conn.execute("UPDATE users SET role=?, approved_ts=?, approved_by=COALESCE(approved_by, ?) WHERE id=?",
                  (role, approved, by, user["id"]))
    conn.commit()
    return get_user(conn, username)


def delete_user(conn: sqlite3.Connection, username: str) -> None:
    user = get_user(conn, username)
    if user is None:
        raise AccountError("USER_NOT_FOUND", "Khong co tai khoan nay")
    if user["role"] == ADMIN and _admin_count(conn) == 1:
        raise AccountError("LAST_ADMIN", "Khong xoa duoc quan tri vien cuoi cung")
    conn.execute("DELETE FROM sessions WHERE user_id=?", (user["id"],))
    conn.execute("DELETE FROM users WHERE id=?", (user["id"],))
    conn.commit()


def change_password(conn: sqlite3.Connection, user_id: int, new_password: str, keep_token: str | None) -> None:
    """Doi mat khau va dang xuat moi thiet bi khac (giu phien dang dung)."""
    username = conn.execute("SELECT username FROM users WHERE id=?", (user_id,)).fetchone()[0]
    if err := check_password(new_password, username):
        raise AccountError("BAD_PASSWORD", err)
    conn.execute("UPDATE users SET pw_hash=? WHERE id=?", (hash_password(new_password), user_id))
    keep = _token_hash(keep_token) if keep_token else ""
    conn.execute("DELETE FROM sessions WHERE user_id=? AND token_hash<>?", (user_id, keep))
    conn.commit()


def reset_accounts(conn: sqlite3.Connection) -> int:
    """Nut reset tren Pi: xoa moi tai khoan va phien. GIU du lieu do va phieu cam nhan."""
    n = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    conn.execute("DELETE FROM sessions")
    conn.execute("DELETE FROM users")
    conn.commit()
    return n


# ------------------------------------------------------------------ phien dang nhap
def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_session(conn: sqlite3.Connection, user_id: int, ts: float, device: str | None = None) -> str:
    token = secrets.token_urlsafe(32)
    conn.execute("INSERT INTO sessions(token_hash, user_id, device, created_ts, last_seen_ts, expires_ts)"
                  " VALUES (?,?,?,?,?,?)",
                  (_token_hash(token), user_id, (device or "").strip()[:60] or None, ts, ts, ts + SESSION_TTL_S))
    conn.commit()
    return token


def session_user(conn: sqlite3.Connection, token: str, now: float) -> dict | None:
    """Nguoi dung cua phien (None neu sai / het han). Gia han khi con dung (toi da moi gio ghi mot lan)."""
    th = _token_hash(token)
    row = conn.execute("SELECT s.last_seen_ts, s.expires_ts, u.id, u.username, u.display_name, u.role,"
                       " u.created_ts, u.approved_ts, u.approved_by"
                       " FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token_hash=?", (th,)).fetchone()
    if row is None:
        return None
    last_seen, expires, *user = row
    if expires <= now:
        conn.execute("DELETE FROM sessions WHERE token_hash=?", (th,))
        conn.commit()
        return None
    if now - last_seen >= SESSION_TOUCH_S:
        conn.execute("UPDATE sessions SET last_seen_ts=?, expires_ts=? WHERE token_hash=?",
                     (now, now + SESSION_TTL_S, th))
        conn.commit()
    return _row_to_user(user)


def end_session(conn: sqlite3.Connection, token: str) -> None:
    conn.execute("DELETE FROM sessions WHERE token_hash=?", (_token_hash(token),))
    conn.commit()


def list_sessions(conn: sqlite3.Connection, user_id: int) -> list[dict]:
    rows = conn.execute("SELECT device, created_ts, last_seen_ts FROM sessions WHERE user_id=?"
                        " ORDER BY last_seen_ts DESC", (user_id,)).fetchall()
    return [{"device": d, "created_ts": c, "last_seen_ts": s} for d, c, s in rows]


# ------------------------------------------------------------------ ma thiet lap / ma thiet bi
def _read_or_create(path: Path, make) -> str:
    try:
        value = path.read_text(encoding="utf-8").strip()
        if value:
            return value
    except FileNotFoundError:
        pass
    value = make()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)   # chi chu so huu doc duoc
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(value + "\n")
    return value


def setup_code(path: Path | None = None) -> str:
    """Ma thiet lap cua Pi nay, tao mot lan roi giu mai (in tren tem). Dang XXXX-XXXX-XXXX (~60 bit)."""
    def make() -> str:
        raw = "".join(secrets.choice(CODE_ALPHABET) for _ in range(12))
        return "-".join(raw[i:i + 4] for i in range(0, 12, 4))
    return _read_or_create(path or SETUP_CODE_FILE, make)


def device_id(path: Path | None = None) -> str:
    """Ma nhan dien Pi (8 ky tu hex), de app biet dang noi dung Pi tren tem."""
    return _read_or_create(path or DEVICE_ID_FILE, lambda: secrets.token_hex(4))


def setup_code_matches(given: str, actual: str) -> bool:
    def norm(s: str) -> str:
        return re.sub(r"[^0-9A-Z]", "", (s or "").upper())
    return hmac.compare_digest(norm(given).encode(), norm(actual).encode())


def setup_uri(code: str, dev_id: str) -> str:
    """Noi dung ma QR tren tem: app Android mo duoc truc tiep."""
    return f"pbl5://setup?id={dev_id}&code={code}"
