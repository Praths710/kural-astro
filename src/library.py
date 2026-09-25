"""Per-user saved leaves ("library"), persisted through store.STORE (Postgres or data/saved.json).

An item keeps everything shown in a reading so it reopens instantly without new AI calls:
the verse, its label/concept, the deep reading, the papers, and the user's own note.
Every field is whitelisted and length-capped: the client cannot store arbitrary data.
"""
import threading
import time

from store import STORE

MAX_ITEMS = 500
_lock = threading.Lock()


def _s(v, n):
    return str(v or "")[:n]


def _clean(raw):
    v = raw.get("verse") if isinstance(raw.get("verse"), dict) else {}
    d = raw.get("deep") if isinstance(raw.get("deep"), dict) else {}
    real = d.get("real_world") if isinstance(d.get("real_world"), list) else []
    papers = raw.get("papers") if isinstance(raw.get("papers"), list) else []
    item_id = _s(raw.get("id") or v.get("id"), 120)
    if not item_id or not _s(v.get("tamil"), 1):
        return None
    return {
        "id": item_id,
        "verse": {k: _s(v.get(k), n) for k, n in
                  (("id", 120), ("source", 40), ("ref", 200), ("tamil", 3000), ("english", 600), ("url", 400),
                   ("label", 4), ("concept", 200), ("meaning", 400))},
        "deep": {"literal": _s(d.get("literal"), 1500), "analogy": _s(d.get("analogy"), 1500),
                 "strength": _s(d.get("strength"), 12),
                 "real_world": [{"title": _s(r.get("title"), 160), "detail": _s(r.get("detail"), 500),
                                 "field": _s(r.get("field"), 40), "organization": _s(r.get("organization"), 80),
                                 "org_type": _s(r.get("org_type"), 30), "year": _s(r.get("year"), 4),
                                 "credible": bool(r.get("credible")),
                                 "url": _s(r.get("url"), 300) if str(r.get("url", "")).startswith("https://") else ""}
                                for r in real[:5] if isinstance(r, dict)]},
        "papers": [{"title": _s(p.get("title"), 300), "url": _s(p.get("url"), 300), "year": _s(p.get("year"), 6),
                    "tag": _s(p.get("tag"), 16), "authors": [_s(a, 80) for a in (p.get("authors") or [])[:4]]}
                   for p in papers[:10] if isinstance(p, dict) and str(p.get("url", "")).startswith("https://arxiv.org/")],
        "note": _s(raw.get("note"), 1000),
    }


def list_items(user):
    return STORE.saved_list(user)


def upsert(user, raw):
    item = _clean(raw if isinstance(raw, dict) else {})
    if not item:
        return None, "Nothing to save."
    with _lock:
        old = STORE.saved_get(user, item["id"])
        if old:
            item["saved_at"] = old.get("saved_at", int(time.time()))
            if not raw.get("note") and old.get("note"):
                item["note"] = old["note"]
            if not item["deep"]["literal"] and old.get("deep", {}).get("literal"):
                item["deep"] = old["deep"]
            if not item["papers"] and old.get("papers"):
                item["papers"] = old["papers"]
        else:
            if STORE.saved_count(user) >= MAX_ITEMS:
                return None, f"Your library is full ({MAX_ITEMS} leaves). Remove some first."
            item["saved_at"] = int(time.time())
        STORE.saved_put(user, item)
    return item, None


def set_note(user, item_id, note):
    with _lock:
        item = STORE.saved_get(user, item_id)
        if not item:
            return False
        item["note"] = _s(note, 1000)
        STORE.saved_put(user, item)
    return True


def remove(user, item_id):
    return STORE.saved_delete(user, item_id)
