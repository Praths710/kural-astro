"""Local web app for the kural-astro project. No installs needed (stdlib only).

Run:  python src/app.py   then open http://localhost:8765

API
  GET  /api/verses                 all Gemini-labeled verses (cached in memory)
  GET  /api/topics                 verse count per physics category (for the cosmic map)
  GET  /api/papers?q=<concept>     live arXiv papers for a concept (no LLM call, fast)
  POST /api/search_topic {topic}   topic -> matching verses (Gemini) + arXiv papers
  POST /api/analyze {text}         any verse -> label + concept (Gemini) + arXiv papers
  POST /api/deep {text, concept}   deep read: literal meaning, the analogy, real-world examples
"""
import json
import os
import subprocess
import sys
import threading
import time
from functools import lru_cache
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import gemini_label as g          # noqa: E402
import research_report as rr      # noqa: E402
import auth                        # noqa: E402
import library                     # noqa: E402

HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", 8765))
MAX_BODY = 64 * 1024
PUBLIC = {"/login", "/login.html", "/health", "/api/login", "/api/signup"}
_arxiv_lock = threading.Lock()
STATIC = ROOT / "src" / "webapp"


@lru_cache(maxsize=1)
def verse_list():
    gem = json.loads((ROOT / "data/labels/gemini_labels_dedup.json").read_text(encoding="utf-8"))
    kurals = {k["Number"]: k for k in json.loads((ROOT / "data/raw/thirukkural.json").read_text(encoding="utf-8"))["kural"]}
    arutpa = {(r["section_id"], r["stanza_no"]): r for r in
              (json.loads(l) for l in (ROOT / "data/processed/thiruvarutpa.jsonl").read_text(encoding="utf-8").splitlines())}
    out = []
    for vid, r in gem.items():
        kind, *rest = vid.split(":")
        if kind == "kural":
            k = kurals.get(int(rest[0]))
            if not k:
                continue
            item = {"source": "Thirukkural", "ref": f"Kural {rest[0]}", "tamil": f"{k['Line1']}\n{k['Line2']}",
                    "english": k.get("Translation", ""), "url": f"https://thirukkural.io/kural/{int(rest[0])}"}
        else:
            sec, stanza = rest[0], int(rest[1])
            v = arutpa.get((sec, stanza))
            if not v:
                continue
            title = v["section_title"].split(". ", 1)[-1]
            item = {"source": "Thiruvarutpa", "ref": f"{title} · stanza {stanza}", "tamil": v["text"],
                    "english": "", "url": v.get("source_url", "")}
        out.append({"id": vid, **item, "label": r.get("label", ""),
                    "concept": r.get("science_concept", ""), "meaning": r.get("meaning", "")})
    order = {"A": 0, "O": 1, "L": 2, "M": 3, "N": 4}
    out.sort(key=lambda v: order.get(v["label"], 9))
    return out


def gemini_json(prompt, attempts=6, temperature=0.2):
    """One Gemini call returning parsed JSON. Body goes via stdin: Windows caps command lines at 32k chars."""
    body = json.dumps({"contents": [{"parts": [{"text": prompt}]}],
                       "generationConfig": {"temperature": temperature, "responseMimeType": "application/json"}})
    for attempt in range(attempts):
        r = subprocess.run(["curl", "-s", "-m", "90", "-H", "Content-Type: application/json", "-H", g.KEY_HEADER, "--data-binary", "@-", g.URL],
                           input=body.encode("utf-8"), capture_output=True)
        try:
            resp = json.loads(r.stdout.decode("utf-8"))
            if "error" in resp:
                code, msg = resp["error"].get("code"), resp["error"].get("message", "")
                if code in (429, 500, 503) or "demand" in msg.lower():
                    time.sleep(min(6 * (attempt + 1), 20))
                    continue
                raise RuntimeError(msg)
            return json.loads(resp["candidates"][0]["content"]["parts"][0]["text"])
        except (json.JSONDecodeError, KeyError, IndexError, UnicodeDecodeError):
            time.sleep(5)
    return None


def match_topic(concept):
    cl = concept.lower()
    for key, (title, trig, queries) in rr.TOPICS.items():
        if any(t in cl for t in trig):
            return key, title, queries
    return None, None, None


def papers_for(concept, key=None):
    if key in rr.TOPICS:
        title, _, queries = rr.TOPICS[key]
    else:
        key, title, queries = match_topic(concept)
    if not queries:
        queries = [f'all:"{concept}"']
        title = "Direct search"
    papers, seen = [], set()
    for q in queries[:2]:
        for tag, sort in (("foundational", "relevance"), ("recent", "submittedDate")):
            try:
                with _arxiv_lock:
                    found = rr.arxiv(q, sort)
            except Exception:
                found = []
            for p in found:
                if p["url"] not in seen:
                    seen.add(p["url"])
                    papers.append({**p, "tag": tag})
    return title, papers


SEARCH_SYS = (
    "You match a research topic against a list of short science-concept phrases extracted from "
    "classical Tamil verses. Return a JSON array of objects {\"id\": <index>, \"reason\": <one sentence>} "
    "for the entries genuinely related to the topic, most relevant first, at most 12. Be selective: "
    "real conceptual links only, not loose word overlap. Empty array if none."
)


def search_by_topic(topic, key=None):
    verses = [v for v in verse_list() if v["label"] in ("L", "O", "A")]
    listing = "\n".join(f'{i}::{v["concept"]}::{v["meaning"]}' for i, v in enumerate(verses))
    raw = gemini_json(temperature=0, prompt=f"{SEARCH_SYS}\n\nTopic: {topic}\n\nList (index::concept::meaning):\n{listing}") or []
    matches = []
    for m in raw if isinstance(raw, list) else []:
        try:
            idx = int(m.get("id", m.get("index", -1)))
        except (TypeError, ValueError, AttributeError):
            continue
        if 0 <= idx < len(verses):
            matches.append({**verses[idx], "reason": m.get("reason", "")})
    topic_title, papers = papers_for(topic, key)
    return {"matches": matches, "topic_title": topic_title, "papers": papers}


DEEP_SYS = (
    "You are explaining a classical Tamil verse to a student project that compares ancient Tamil texts "
    "with modern astrophysics. Be honest: the poet did not know modern science; this is an analogy. "
    "Return JSON with keys:\n"
    "  literal: 2-3 sentences, what the verse actually says in its own religious/ethical context\n"
    "  analogy: 2-3 sentences, how its imagery resembles the given modern science concept, and where the resemblance breaks down\n"
    "  real_world: array of 3 objects {title, detail} -- real, well-documented modern observations, experiments, "
    "missions or technologies related to that concept (e.g. named telescopes, missions, experiments with years). "
    "Only use things you are confident exist; no invented projects.\n"
    "  strength: one of 'strong', 'moderate', 'weak' -- how close the analogy honestly is"
)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _send(self, code, body, ctype="application/json", headers=()):
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        for k, v in headers:
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _json(self, code, obj, headers=()):
        self._send(code, json.dumps(obj, ensure_ascii=False), headers=headers)

    def _redirect(self, to):
        self.send_response(302)
        self.send_header("Location", to)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _secure(self):
        return self.headers.get("X-Forwarded-Proto", "").lower() == "https"

    def _ip(self):
        return (self.headers.get("X-Forwarded-For") or self.client_address[0]).split(",")[0].strip()

    def _user(self):
        c = SimpleCookie(self.headers.get("Cookie", ""))
        return auth.read_token(c[auth.COOKIE].value) if auth.COOKIE in c else None

    def _static(self, name):
        f = STATIC / name
        if f.is_file() and f.resolve().is_relative_to(STATIC.resolve()):
            ctype = {"html": "text/html", "css": "text/css", "js": "application/javascript",
                     "svg": "image/svg+xml"}.get(f.suffix.lstrip("."), "text/plain")
            return self._send(200, f.read_bytes(), ctype, headers=[("Cache-Control", "no-cache")])
        self._json(404, {"error": "not found"})

    def _gate(self, path):
        """Return the signed-in username (or '' for public paths); otherwise send 401/redirect and return None."""
        user = self._user()
        if user or path in PUBLIC:
            return user or ""
        if path.startswith("/api/"):
            self._json(401, {"error": "Please sign in."})
        else:
            self._redirect("/login")
        return None

    def do_GET(self):
        url = urlparse(self.path)
        path = url.path
        if path == "/health":
            return self._json(200, {"ok": True})
        if path == "/api/config":
            return self._json(200, {"invite_required": bool(os.environ.get("INVITE_CODE"))})
        if path in ("/login", "/login.html"):
            return self._redirect("/") if self._user() else self._static("login.html")
        user = self._gate(path)
        if user is None:
            return
        if path in ("/", "/index.html"):
            return self._static("index.html")
        if path == "/api/me":
            return self._json(200, {"username": user})
        if path == "/api/saved":
            return self._json(200, library.list_items(user))
        if path == "/api/verses":
            return self._json(200, verse_list())
        if path == "/api/topics":
            counts = {k: {"title": t[0], "count": 0} for k, t in rr.TOPICS.items()}
            for v in verse_list():
                if v["label"] in ("L", "O", "A"):
                    key, *_ = match_topic(v["concept"])
                    if key:
                        counts[key]["count"] += 1
            return self._json(200, counts)
        if path == "/api/papers":
            q = (parse_qs(url.query).get("q") or [""])[0].strip()[:200]
            if not q:
                return self._json(400, {"error": "empty q"})
            title, papers = papers_for(q)
            return self._json(200, {"topic_title": title, "papers": papers})
        self._static(path.lstrip("/"))

    def do_POST(self):
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length", 0) or 0)
        if length > MAX_BODY:
            return self._json(413, {"error": "Request too large."})
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(body, dict):
                raise ValueError
        except ValueError:
            return self._json(400, {"error": "Bad request."})

        if path == "/api/login":
            user, err = auth.check_login(body.get("username", ""), body.get("password", ""), self._ip())
            if err:
                return self._json(401, {"error": err})
            cookie = auth.cookie_header(auth.make_token(user), self._secure())
            return self._json(200, {"username": user}, headers=[("Set-Cookie", cookie)])
        if path == "/api/signup":
            username = (body.get("username") or "").strip()
            err = auth.create_user(username, body.get("password", ""), body.get("invite", ""))
            if err:
                return self._json(400, {"error": err})
            cookie = auth.cookie_header(auth.make_token(username), self._secure())
            return self._json(200, {"username": username}, headers=[("Set-Cookie", cookie)])
        if path == "/api/logout":
            return self._json(200, {"ok": True}, headers=[("Set-Cookie", auth.cookie_header("", self._secure(), clear=True))])

        user = self._gate(path)
        if user is None:
            return
        if path == "/api/saved":
            item, err = library.upsert(user, body)
            return self._json(400, {"error": err}) if err else self._json(200, item)
        if path == "/api/saved/delete":
            return self._json(200, {"ok": library.remove(user, str(body.get("id", "")))})
        if path == "/api/saved/note":
            return self._json(200, {"ok": library.set_note(user, str(body.get("id", "")), body.get("note", ""))})
        if path == "/api/search_topic":
            topic = (body.get("topic") or "").strip()[:200]
            if not topic:
                return self._json(400, {"error": "empty topic"})
            return self._json(200, search_by_topic(topic, body.get("key")))
        if path == "/api/analyze":
            text = (body.get("text") or "").strip()
            if not text:
                return self._json(400, {"error": "empty text"})
            verse = json.dumps({"id": "adhoc", "text": text[:1500]}, ensure_ascii=False)
            result = gemini_json(f"{g.SYSTEM}\n\nVerses:\n{verse}", attempts=4, temperature=0)
            if isinstance(result, dict):
                result = [result]
            if not result or not isinstance(result[0], dict):
                return self._json(502, {"error": "The AI service is busy. Try again in a few seconds."})
            r = result[0]
            topic_title, papers = None, []
            if r.get("label") in ("L", "O", "A") and r.get("science_concept"):
                topic_title, papers = papers_for(r["science_concept"])
            return self._json(200, {**r, "topic_title": topic_title, "papers": papers})
        if path == "/api/deep":
            text, concept = (body.get("text") or "").strip()[:2000], (body.get("concept") or "").strip()[:200]
            if not text:
                return self._json(400, {"error": "empty text"})
            out = gemini_json(f"{DEEP_SYS}\n\nVerse: {text}\nModern concept: {concept or '(none identified)'}")
            if not isinstance(out, dict):
                return self._json(502, {"error": "The AI service is busy. Try again in a few seconds."})
            return self._json(200, out)
        self._json(404, {"error": "not found"})


def main():
    verse_list()
    if not g.KEY:
        print("WARNING: GEMINI_API_KEY is not set -- AI features will fail.", flush=True)
    shown = "localhost" if HOST in ("127.0.0.1", "0.0.0.0") else HOST
    print(f"kural-astro app running at http://{shown}:{PORT}  (Ctrl+C to stop)", flush=True)
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
