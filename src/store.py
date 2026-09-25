"""Persistence for accounts and saved leaves.

DATABASE_URL set (env or .env)  -> Postgres (e.g. Neon/Supabase free tier): survives redeploys.
otherwise                        -> JSON files under data/ (local development).
Both backends expose the same functions, used by auth.py and library.py.
"""
import json
import os
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _env(name):
    if os.environ.get(name):
        return os.environ[name].strip()
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.startswith(name + "="):
                return line.split("=", 1)[1].strip()
    return ""


class JsonStore:
    kind = "json-files"

    def __init__(self):
        self.users = Path(os.environ.get("USERS_FILE", ROOT / "data" / "users.json"))
        self.saved = Path(os.environ.get("SAVED_FILE", ROOT / "data" / "saved.json"))
        self.cache = ROOT / "data" / "cache.json"
        self.shares = ROOT / "data" / "shares.json"
        self.lock = threading.Lock()

    @staticmethod
    def _read(p):
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}

    @staticmethod
    def _write(p, data):
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        tmp.replace(p)

    def find_user(self, username):
        users = self._read(self.users)
        name = next((u for u in users if u.lower() == (username or "").lower()), None)
        return (name, users[name]["salt"], users[name]["hash"]) if name else None

    def add_user(self, username, salt, pw_hash):
        with self.lock:
            users = self._read(self.users)
            if username.lower() in {u.lower() for u in users}:
                return False
            users[username] = {"salt": salt, "hash": pw_hash, "created": int(time.time())}
            self._write(self.users, users)
        return True

    def saved_list(self, user):
        return sorted(self._read(self.saved).get(user, []), key=lambda i: -i.get("saved_at", 0))

    def saved_get(self, user, item_id):
        return next((i for i in self._read(self.saved).get(user, []) if i["id"] == item_id), None)

    def saved_count(self, user):
        return len(self._read(self.saved).get(user, []))

    def saved_put(self, user, item):
        with self.lock:
            data = self._read(self.saved)
            items = [i for i in data.get(user, []) if i["id"] != item["id"]]
            data[user] = [item] + items
            self._write(self.saved, data)

    def cache_get(self, key, max_age=None):
        e = self._read(self.cache).get(key)
        if not e or (max_age and time.time() - e["t"] > max_age):
            return None
        return e["v"]

    def cache_put(self, key, value):
        with self.lock:
            d = self._read(self.cache)
            d[key] = {"t": int(time.time()), "v": value}
            self._write(self.cache, d)

    def share_put(self, sid, owner, item):
        with self.lock:
            d = self._read(self.shares)
            d[sid] = {"owner": owner, "t": int(time.time()), "item": item}
            self._write(self.shares, d)

    def share_get(self, sid):
        e = self._read(self.shares).get(sid)
        return e["item"] if e else None

    def saved_delete(self, user, item_id):
        with self.lock:
            data = self._read(self.saved)
            items = data.get(user, [])
            kept = [i for i in items if i["id"] != item_id]
            if len(kept) == len(items):
                return False
            data[user] = kept
            self._write(self.saved, data)
        return True


class PgStore:
    kind = "postgres"
    SCHEMA = """
    CREATE TABLE IF NOT EXISTS users (
        username TEXT PRIMARY KEY, salt TEXT NOT NULL, hash TEXT NOT NULL, created BIGINT NOT NULL);
    CREATE UNIQUE INDEX IF NOT EXISTS users_lower_idx ON users (lower(username));
    CREATE TABLE IF NOT EXISTS saved (
        username TEXT NOT NULL REFERENCES users(username) ON DELETE CASCADE,
        id TEXT NOT NULL, saved_at BIGINT NOT NULL, item JSONB NOT NULL,
        PRIMARY KEY (username, id));
    CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, created BIGINT NOT NULL, value JSONB NOT NULL);
    CREATE TABLE IF NOT EXISTS shares (id TEXT PRIMARY KEY, owner TEXT, created BIGINT NOT NULL, item JSONB NOT NULL);
    """

    def __init__(self, url):
        import psycopg
        from psycopg.types.json import Jsonb
        self.psycopg, self.Jsonb, self.url = psycopg, Jsonb, url
        self.conn, self.lock = None, threading.Lock()
        self._q(self.SCHEMA)

    def _q(self, sql, args=(), fetch=None):
        with self.lock:
            for attempt in (1, 2):
                try:
                    if self.conn is None or self.conn.closed:
                        self.conn = self.psycopg.connect(self.url, autocommit=True, connect_timeout=15)
                    with self.conn.cursor() as cur:
                        cur.execute(sql, args)
                        if fetch == "one":
                            return cur.fetchone()
                        if fetch == "all":
                            return cur.fetchall()
                        return cur.rowcount
                except self.psycopg.OperationalError:
                    self.conn = None  # free-tier databases drop idle connections; reconnect once
                    if attempt == 2:
                        raise

    def find_user(self, username):
        return self._q("SELECT username, salt, hash FROM users WHERE lower(username) = lower(%s)", (username or "",), "one")

    def add_user(self, username, salt, pw_hash):
        try:
            self._q("INSERT INTO users (username, salt, hash, created) VALUES (%s, %s, %s, %s)",
                    (username, salt, pw_hash, int(time.time())))
            return True
        except self.psycopg.errors.UniqueViolation:
            return False

    def saved_list(self, user):
        return [r[0] for r in self._q("SELECT item FROM saved WHERE username = %s ORDER BY saved_at DESC", (user,), "all")]

    def saved_get(self, user, item_id):
        r = self._q("SELECT item FROM saved WHERE username = %s AND id = %s", (user, item_id), "one")
        return r[0] if r else None

    def saved_count(self, user):
        return self._q("SELECT count(*) FROM saved WHERE username = %s", (user,), "one")[0]

    def saved_put(self, user, item):
        self._q("""INSERT INTO saved (username, id, saved_at, item) VALUES (%s, %s, %s, %s)
                   ON CONFLICT (username, id) DO UPDATE SET item = EXCLUDED.item, saved_at = EXCLUDED.saved_at""",
                (user, item["id"], item.get("saved_at", int(time.time())), self.Jsonb(item)))

    def cache_get(self, key, max_age=None):
        r = self._q("SELECT value, created FROM cache WHERE key = %s", (key,), "one")
        if not r or (max_age and time.time() - r[1] > max_age):
            return None
        return r[0]

    def cache_put(self, key, value):
        self._q("""INSERT INTO cache (key, created, value) VALUES (%s, %s, %s)
                   ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, created = EXCLUDED.created""",
                (key, int(time.time()), self.Jsonb(value)))

    def share_put(self, sid, owner, item):
        self._q("INSERT INTO shares (id, owner, created, item) VALUES (%s, %s, %s, %s)",
                (sid, owner, int(time.time()), self.Jsonb(item)))

    def share_get(self, sid):
        r = self._q("SELECT item FROM shares WHERE id = %s", (sid,), "one")
        return r[0] if r else None

    def saved_delete(self, user, item_id):
        return self._q("DELETE FROM saved WHERE username = %s AND id = %s", (user, item_id)) > 0


_url = "" if os.environ.get("STORE") == "json" else _env("DATABASE_URL")  # STORE=json forces local files
STORE = PgStore(_url) if _url else JsonStore()
