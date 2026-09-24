"""Accounts and sessions for the web app (stdlib only).

Passwords: PBKDF2-HMAC-SHA256, 200k iterations, per-user random salt.
Sessions: stateless signed cookie "user|expiry|hmac" keyed by SECRET_KEY (env) or an
auto-generated data/.secret. Users live in data/users.json (or USERS_FILE env).
If INVITE_CODE is set in the environment, sign-up requires it.
"""
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
USERS = Path(os.environ.get("USERS_FILE", ROOT / "data" / "users.json"))
COOKIE = "ka_session"
MAX_AGE = 7 * 24 * 3600
ITER = 200_000
_lock = threading.Lock()
_fails = {}  # ip -> [timestamps of failed logins]


def _secret():
    if os.environ.get("SECRET_KEY"):
        return os.environ["SECRET_KEY"].encode()
    p = ROOT / "data" / ".secret"
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(secrets.token_hex(32))
    return p.read_text().strip().encode()


SECRET = _secret()


def _load():
    return json.loads(USERS.read_text(encoding="utf-8")) if USERS.exists() else {}


def _hash(password, salt):
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), ITER).hex()


def validate(username, password):
    if not re.fullmatch(r"[A-Za-z0-9_.-]{3,32}", username or ""):
        return "Username must be 3–32 characters: letters, numbers, _ . -"
    if len(password or "") < 8:
        return "Password must be at least 8 characters."
    return None


def create_user(username, password, invite=""):
    need = os.environ.get("INVITE_CODE", "")
    if need and not hmac.compare_digest(need, invite or ""):
        return "That invite code is not valid."
    err = validate(username, password)
    if err:
        return err
    with _lock:
        users = _load()
        if username.lower() in {u.lower() for u in users}:
            return "That username is taken."
        salt = secrets.token_hex(16)
        users[username] = {"salt": salt, "hash": _hash(password, salt), "created": int(time.time())}
        USERS.parent.mkdir(parents=True, exist_ok=True)
        tmp = USERS.with_suffix(".tmp")
        tmp.write_text(json.dumps(users, indent=1), encoding="utf-8")
        tmp.replace(USERS)
    return None


def too_many_failures(ip):
    now = time.time()
    recent = [t for t in _fails.get(ip, []) if now - t < 600]
    _fails[ip] = recent
    return len(recent) >= 10


def check_login(username, password, ip):
    if too_many_failures(ip):
        return None, "Too many attempts. Wait 10 minutes and try again."
    users = _load()
    match = next((u for u in users if u.lower() == (username or "").lower()), None)
    if match and hmac.compare_digest(users[match]["hash"], _hash(password or "", users[match]["salt"])):
        return match, None
    _fails.setdefault(ip, []).append(time.time())
    return None, "Wrong username or password."


def make_token(username):
    payload = f"{username}|{int(time.time()) + MAX_AGE}"
    sig = hmac.new(SECRET, payload.encode(), hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(f"{payload}|{sig}".encode()).decode()


def read_token(token):
    try:
        username, exp, sig = base64.urlsafe_b64decode(token.encode()).decode().rsplit("|", 2)
    except Exception:
        return None
    good = hmac.new(SECRET, f"{username}|{exp}".encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(good, sig) or int(exp) < time.time():
        return None
    return username if username in _load() else None


def cookie_header(token, secure, clear=False):
    attrs = [f"{COOKIE}={'' if clear else token}", "Path=/", "HttpOnly", "SameSite=Lax",
             f"Max-Age={0 if clear else MAX_AGE}"]
    if secure:
        attrs.append("Secure")
    return "; ".join(attrs)
