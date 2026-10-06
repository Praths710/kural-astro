"""Local web app for the kural-astro project. No installs needed (stdlib only).

Run:  python src/app.py   then open http://localhost:8765

API
  GET  /api/verses                 all Gemini-labeled verses (cached in memory)
  GET  /api/topics                 verse count per physics category (for the cosmic map)
  GET  /api/papers?q=<concept>     papers from official publishers (Crossref: IEEE, Springer, AAS...) + NASA NTRS
  GET  /api/images?q=<concept>     official images from the NASA Image and Video Library
  POST /api/search_topic {topic}   topic -> matching verses (Gemini) + official papers
  POST /api/analyze {text}         any verse -> label + concept (Gemini) + official papers
  POST /api/deep {text, concept}   deep read: literal meaning, the analogy, real-world examples
"""
import hashlib
import json
import os
import re
import secrets
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import gemini_label as g          # noqa: E402
import research_report as rr      # noqa: E402
import official_sources as osrc   # noqa: E402
import auth                        # noqa: E402
import library                     # noqa: E402
from store import STORE            # noqa: E402

HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", 8765))
MAX_BODY = 64 * 1024
PUBLIC = {"/login", "/login.html", "/health", "/api/login", "/api/signup"}
DAY = 86400
TAMIL = re.compile(r"[\u0B80-\u0BFF]")
LANG_NOTE = {"en": "", "ta": ("\nWrite every text value in clear, modern Tamil (தமிழ்). Keep names of missions, telescopes "
                               "and scientific terms understandable (you may add the English name in brackets).")}


def ckey(*parts):
    return hashlib.sha256("\x1f".join(str(x) for x in parts).encode("utf-8")).hexdigest()


def cached(key, max_age, compute, fresh=False):
    """Serve from the shared cache; compute (an AI or arXiv call) only on a miss. Failed results are never cached."""
    if not fresh:
        hit = STORE.cache_get(key, max_age)
        if hit is not None:
            return hit
    value = compute()
    if value:
        STORE.cache_put(key, value)
    return value
_arxiv_lock = threading.Lock()
STARTED = time.time()
_health_hits = []
STATIC = ROOT / "src" / "webapp"


@lru_cache(maxsize=1)
def verse_list():
    gem = json.loads((ROOT / "data/labels/gemini_labels_dedup.json").read_text(encoding="utf-8"))
    kurals = {k["Number"]: k for k in json.loads((ROOT / "data/raw/thirukkural.json").read_text(encoding="utf-8"))["kural"]}
    arutpa = {(r["section_id"], r["stanza_no"]): r for r in
              (json.loads(l) for l in (ROOT / "data/processed/thiruvarutpa.jsonl").read_text(encoding="utf-8").splitlines())}
    jl = lambda name: [json.loads(l) for l in (ROOT / f"data/processed/{name}.jsonl").read_text(encoding="utf-8").splitlines()
                       if l.strip()] if (ROOT / f"data/processed/{name}.jsonl").exists() else []
    tolka = {r["no"]: r for r in (jl("tolkappiyam_text") or jl("tolkappiyam"))}
    pavai = {r["no"]: r for r in jl("thiruppavai")}
    out = []
    for vid, r in gem.items():
        kind, *rest = vid.split(":")
        if kind not in ("kural", "arutpa", "tolka", "pavai"):
            continue
        if kind == "kural":
            k = kurals.get(int(rest[0]))
            if not k:
                continue
            item = {"source": "Thirukkural", "ref": f"Kural {rest[0]}", "tamil": f"{k['Line1']}\n{k['Line2']}",
                    "english": k.get("Translation", ""), "url": f"https://thirukkural.io/kural/{int(rest[0])}"}
        elif kind == "arutpa":
            sec, stanza = rest[0], int(rest[1])
            v = arutpa.get((sec, stanza))
            if not v:
                continue
            title = v["section_title"].split(". ", 1)[-1]
            item = {"source": "Thiruvarutpa", "ref": f"{title} · stanza {stanza}", "tamil": v["text"],
                    "english": "", "url": v.get("source_url", "")}
        elif kind == "tolka":
            v = tolka.get(int(rest[0]))
            if not v:
                continue
            item = {"source": "Tolkappiyam", "ref": f"{v['iyal']} · sutra {v['no']}", "tamil": v["text"],
                    "english": "", "url": v["source_url"]}
        elif kind == "pavai":
            v = pavai.get(int(rest[0]))
            if not v:
                continue
            item = {"source": "Thiruppavai", "ref": f"Andal · pasuram {v['no']}", "tamil": v["text"],
                    "english": "", "url": v["source_url"]}
        out.append({"id": vid, **item, "label": r.get("label", ""),
                    "concept": r.get("science_concept", ""), "meaning": r.get("meaning", "")})
    # the site is about astronomy and astrophysics only: a science verse counts when its idea lands in an astro theme
    for v in out:
        key = match_topic(v["concept"])[0] if v["label"] in ("L", "O", "A") else None
        v["theme"] = key if key in rr.ASTRO_THEMES else None
    # second, astronomy-only pass (astro_pass.py): sky verses the broad first pass had filed as metaphor or no science
    extra = ROOT / "data/labels/astro_accepted.json"
    if extra.exists():
        accepted = json.loads(extra.read_text(encoding="utf-8"))
        for v in out:
            a = accepted.get(v["id"])
            if a and not v["theme"]:
                v.update(label=a["label"], theme=a["theme"], concept=a["concept"], meaning=a["meaning"])
    for v in out:
        v["astro"] = bool(v["theme"])
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
    cl = concept.lower() + " "   # trailing space lets a trigger like "star " match a last word
    for key, (title, trig, queries) in rr.TOPICS.items():
        # triggers match at the start of a word, so "sea" does not fire inside "disease"
        if any(re.search(r"\b" + re.escape(t), cl) for t in trig):
            return key, title, queries
    return None, None, None


def papers_for(concept, key=None, must=None):
    """must: core words every paper title has to contain (the rest of `concept` only helps ranking)."""
    out = cached(ckey("papers-v10", key or "", concept.lower(), (must or "").lower()), 7 * DAY,
                 lambda: _papers_live(concept, key, must))
    papers = sorted((out or {}).get("papers", []), key=lambda p: -int(re.sub(r"\D", "", str(p.get("year") or "")) or 0))
    return (out or {}).get("title"), papers


def _papers_live(concept, key=None, must=None):
    if must:   # a search topic with an AI search phrase: query it directly, no theme matching
        papers = osrc.papers(concept, must)
        return {"title": "Direct search", "papers": papers} if papers else None
    if key in rr.TOPICS:
        title, _, queries = rr.TOPICS[key]
    else:
        key, title, queries = match_topic(concept)
    if not queries:
        # a poetic concept phrase rarely matches a paper title: let the AI turn it into a scientific search phrase
        u = understand_query(concept) if not is_plain_term(concept) else None
        queries = [u["arxiv"], u["topic"]] if u else [concept]
        title = "Direct search"
    papers, seen = [], set()
    for q in list(dict.fromkeys(osrc.plain_query(x) for x in queries))[:4]:
        for p in osrc.papers(q):
            if p["url"] not in seen:
                seen.add(p["url"])
                papers.append(p)
        if len(papers) >= 8:
            break
    return {"title": title, "papers": papers} if papers else None


SEARCH_SYS = (
    "You match a research topic against a list of short science-concept phrases extracted from classical Tamil verses. "
    "Match by MEANING (semantic similarity), not by shared words. Return a JSON array of objects "
    "{\"id\": <index>, \"reason\": <one or two sentences explaining why this verse relates to the topic>, "
    "\"match_type\": one of \"direct\" (the verse describes the same phenomenon), \"analogy\" (its imagery parallels the topic), "
    "\"thematic\" (a broader shared theme), \"possible\" (not an established link, but there is a real chance of a relation "
    "worth a student's look -- say in the reason what the possible link is and why it is uncertain), "
    "\"matched_on\": <the specific idea or image in the verse that matches>, \"score\": <relevance 1-5>}. "
    "Give ALL genuine matches (direct/analogy/thematic), up to 40, most relevant first, then up to 8 extra 'possible' ones (score 1-2). "
    "No random filler: every entry needs a concrete reason. Empty array if none. The list mixes four works "
    "(Thirukkural, Thiruvarutpa, Tolkappiyam, Thiruppavai): judge every entry on its own merit, whatever work it comes from."
)
MATCH_TYPES = ("direct", "analogy", "thematic", "possible")
SEARCH_STOP = {"and", "the", "of", "in", "on", "a", "an", "to", "for", "with", "what", "did", "does", "do", "is", "are", "was",
               "were", "they", "poets", "poet", "verse", "verses", "about", "know", "knew", "tamil", "ancient", "inside",
               "there", "this", "that", "how", "why", "when", "who", "say", "said", "any", "all", "from", "into", "their"}


WORD_START = chr(92) + "b"   # regex word boundary


def topic_words(text):
    """Search words for the word match: plural 's' dropped ('atoms' -> 'atom'), short and common words ignored."""
    out = set()
    for w in re.findall(r"[a-z]{3,}", (text or "").lower()):
        if w in SEARCH_STOP:
            continue
        out.add(w[:-1] if len(w) > 4 and w.endswith("s") and not w.endswith("ss") else w)
    return out


def english_query(topic):
    """arXiv only understands English: translate a Tamil search term once and cache it."""
    if not TAMIL.search(topic):
        return topic
    out = cached(ckey("q-en", topic), None, lambda: gemini_json(
        'Translate this search term into a short English scientific search phrase. Return JSON {"q": "..."}.\nTerm: ' + topic,
        attempts=3, temperature=0))
    return (out or {}).get("q") or topic


UNDERSTAND_SYS = (
    "A student typed this into the search box of an app that finds classical Tamil verses (Thirukkural, Thiruvarutpa) "
    "echoing modern science. It may be a keyword, a question, a sentence, slang, a typo, Tamil or a mix. "
    "Work out what they want to find. Return JSON {\"topic\": the pure modern-science idea to search for, 1-4 English words, "
    "e.g. 'atoms', 'water cycle', 'nested universes' -- never add words like ancient, Tamil, verses, literature or history, "
    "\"arxiv\": a short English physics/science phrase for searching research papers (again no ancient/literature words), "
    "\"intent\": one sentence in plain English starting 'You want' describing what they are looking for, "
    "\"related\": 3 related topics they could try next (1-3 words each)}.\n"
)


def is_plain_term(text):
    """A short English keyword like 'atoms' or 'dark matter' needs no interpretation."""
    return not TAMIL.search(text) and "?" not in text and len(text.split()) <= 3


def understand_query(text):
    """Turn free text ('which verses talk about tiny particles?') into a clean topic. Cached; None if the AI is busy."""
    out = cached(ckey("understand-v2", text.lower()), None,
                 lambda: gemini_json(UNDERSTAND_SYS + "Search box text: " + text, attempts=3, temperature=0))
    if not isinstance(out, dict) or not str(out.get("topic") or "").strip():
        return None
    rel = [str(r)[:40] for r in (out.get("related") or []) if isinstance(r, str)][:4]
    return {"topic": str(out["topic"]).strip()[:80], "arxiv": str(out.get("arxiv") or out["topic"]).strip()[:120],
            "intent": str(out.get("intent") or "").strip()[:300], "related": rel}


def search_by_topic(topic, key=None, lang="en"):
    return cached(ckey("search-v14-theme" if key else "search-v12-astro", topic.lower(), key or "", lang), 7 * DAY, lambda: _search_live(topic, key, lang))


@lru_cache(maxsize=1)
def interleaved_science_verses():
    """Science verses taken round-robin from each text, so no text sits at the top of the list the AI reads."""
    by_src = {}
    for v in verse_list():
        if v["astro"]:
            by_src.setdefault(v["source"], []).append(v)
    out, queues = [], list(by_src.values())
    while any(queues):
        for q in queues:
            if q:
                out.append(q.pop(0))
    return out


def _search_live(topic, key=None, lang="en"):
    understood = None if key or is_plain_term(topic) else understand_query(topic)
    ask = f"{understood['topic']} (the student typed: \"{topic}\" -- meaning: {understood['intent']})" if understood else topic
    verses = interleaved_science_verses()
    listing = "\n".join(f'{i}::{v["source"]}::{v["concept"]}::{v["meaning"]}' for i, v in enumerate(verses))
    reason_lang = " Write each reason in Tamil." if lang == "ta" else ""
    prompt = f"{SEARCH_SYS}{reason_lang}\n\nTopic: {ask}\n\nList (index::work::concept::meaning):\n{listing}"
    raw = gemini_json(temperature=0, prompt=prompt)
    if raw == []:   # an empty answer is sometimes a fluke: ask once more before caching "no verses" for a week
        raw = gemini_json(temperature=0.3, prompt=prompt)
    if raw is None:
        return None
    raw = raw or []
    matches = []
    for m in raw if isinstance(raw, list) else []:
        try:
            idx = int(m.get("id", m.get("index", -1)))
        except (TypeError, ValueError, AttributeError):
            continue
        if 0 <= idx < len(verses):
            try:
                score = max(1, min(5, int(m.get("score") or 3)))
            except (TypeError, ValueError):
                score = 3
            mt = m.get("match_type") if m.get("match_type") in MATCH_TYPES else "thematic"
            if mt == "possible":
                score = min(score, 2)
            matches.append({**verses[idx], "reason": m.get("reason", ""), "match_type": mt,
                            "matched_on": m.get("matched_on", ""), "score": score})
    seen = set()
    matches = [m for m in matches if not (m["id"] in seen or seen.add(m["id"]))]
    # word search on top of the AI: every science verse whose concept or meaning contains the search words is
    # included, so a topic like "atoms" returns all its verses rather than only the ones the AI chose to list
    words = set() if key else topic_words(understood["topic"] if understood else topic) | topic_words(topic)
    if key:
        # a planet on the cosmic map: show exactly that theme's verses, so the count matches the number on the map.
        # the AI still supplies the reason for those it picked; anything else it picked becomes a possible link.
        in_theme = {v["id"] for v in verses if v["theme"] == key}
        title = topic
        for m in matches:
            if m["id"] not in in_theme:
                m["match_type"], m["score"] = "possible", min(m["score"], 2)
            elif m["match_type"] == "possible":
                m["match_type"] = "thematic"
        chosen = {m["id"] for m in matches}
        matches += [{**v, "match_type": "thematic", "score": 2, "matched_on": title,
                     "reason": f'Its science concept, "{v["concept"]}", belongs to the {title} theme.'}
                    for v in verses if v["id"] in in_theme and v["id"] not in chosen]
    if words:
        chosen = {m["id"] for m in matches}
        for v in verses:
            text = f'{v["concept"]} {v["meaning"]}'.lower()
            hits = sorted(w for w in words if re.search(WORD_START + re.escape(w), text))
            if hits and v["id"] not in chosen:
                matches.append({**v, "match_type": "keyword", "score": 2 if len(hits) > 1 else 1, "matched_on": ", ".join(hits),
                                "reason": f'Its science concept, "{v["concept"]}", mentions {", ".join(hits)}.'})
    rank = {"direct": 0, "analogy": 1, "thematic": 2, "keyword": 3, "possible": 4}
    matches.sort(key=lambda v: (rank.get(v["match_type"], 5), -v["score"]))
    # a one-word topic ("Seasons") is too vague for a paper search: use the AI's scientific search phrase when there is one
    if not understood and not key and not match_topic(topic)[0]:
        understood_for_papers = understand_query(topic)
    else:
        understood_for_papers = understood
    if understood_for_papers and not key:
        u = understood_for_papers
        topic_title, papers = papers_for(f'{u["topic"]} {u["arxiv"]}', None, must=u["topic"])
    else:
        topic_title, papers = papers_for(english_query(topic), key)
    return {"matches": matches, "topic_title": topic_title, "papers": papers, "understood": understood}


def concept_translations(lang):
    """One cached AI call maps every concept phrase in the dataset to Tamil for the Tamil interface."""
    if lang != "ta":
        return {}
    phrases = sorted({v["concept"] for v in verse_list() if v["label"] in ("L", "O", "A") and v["concept"]})
    out = {}
    for i in range(0, len(phrases), 80):
        chunk = phrases[i:i + 80]
        part = cached(ckey("concepts-ta", *chunk), None, lambda c=chunk: gemini_json(
            "Translate each English science phrase into concise, natural modern Tamil. "
            "Return a JSON object mapping each original phrase exactly to its Tamil translation.\n" + json.dumps(c, ensure_ascii=False),
            attempts=4, temperature=0))
        if isinstance(part, dict):
            out.update({k: v for k, v in part.items() if isinstance(v, str)})
    return out


FIELDS = ["Space & Astronomy", "Physics", "Earth & Climate", "Water & Oceans", "Medicine & Health", "Biology & Life",
          "Agriculture & Food", "Energy", "Technology & Engineering", "Mathematics & Computing", "Economy & Finance",
          "Environment & Ecology"]
CREDIBLE = {"space agency": 0, "university": 0, "research institute": 1, "government": 1, "company": 2}

OBS_METHODS = ["Radio spectral imaging", "Photometry", "Cosmology", "Beta scaling", "Petascale data", "Visualisation"]

DEEP_SYS = (
    "You are explaining a classical Tamil verse to a student project that compares ancient Tamil texts "
    "with modern science. Be honest: the poet did not know modern science; this is an analogy. Write clearly for a student.\n"
    "Return JSON with keys:\n"
    "  literal: 3-4 sentences -- what the verse actually says, in plain English, in its own religious/ethical context\n"
    "  key_words: array of 2-5 {tamil, transliteration, meaning} -- the Tamil words in the verse that carry its natural or "
    "cosmic imagery (copy the Tamil exactly as it appears in the verse)\n"
    "  context: 1-2 sentences -- where the verse sits (its Thirukkural chapter, Thiruvarutpa hymn, Tolkappiyam "
    "section or Thiruppavai pasuram) and how "
    "traditional commentators read it\n"
    "  analogy: 3-4 sentences -- the modern science concept and exactly how the verse's imagery maps onto it\n"
    "  similarities: array of 2-3 short points where the verse and the science genuinely line up\n"
    "  differences: array of 2-3 short points where the analogy breaks down\n"
    "  strength: one of 'strong', 'moderate', 'weak' -- how close the analogy honestly is\n"
    "  strength_reason: one sentence explaining that rating\n"
    "  real_world: array of 4-6 objects {title, detail, field, domain_reason, organization, org_type, year, url} -- real, "
    "well-documented modern missions, experiments, observations, studies or technologies connected to the concept, "
    "spread across every domain it genuinely touches (health, water, food, energy, economy... not only space).\n"
    "    field: the domain, exactly one of " + ", ".join(FIELDS) + "\n"
    "    domain_reason: a short phrase saying why this example belongs to that domain (what it studies)\n"
    "    organization: who did it -- strongly prefer top credible bodies: NASA, ISRO, ESA, JAXA, CNSA, Roscosmos, CERN, "
    "NOAA, WHO, FAO, IMF, World Bank, and leading universities (Stanford, MIT, Caltech, Harvard, Oxford, Cambridge, IISc, IITs...)\n"
    "    org_type: one of 'space agency', 'university', 'research institute', 'government', 'company', 'other'\n"
    "    year: the year of the mission or result (number)\n"
    "    url: the official page URL only if you are confident it exists, otherwise an empty string\n"
    "    Only use things you are confident exist; no invented projects.\n"
    "  hypotheses: array of 2-3 objects {kind, title, statement, inspired_by, how_to_test, prediction, field} -- NEW ideas a "
    "researcher could build today, inspired by the verse's imagery (not claims that the poet knew science):\n"
    "    kind: one of 'testable hypothesis' (a falsifiable scientific claim), 'theoretical idea' (a model or thought experiment), "
    "'application idea' (a technology, AI/ML system or project someone could build)\n"
    "    title: a short name for the idea (max 8 words)\n"
    "    statement: 1-2 crisp sentences (max 45 words) stating the hypothesis or idea precisely\n"
    "    inspired_by: the Tamil words of the verse that sparked it, with a 3-6 word English gloss (max 15 words)\n"
    "    how_to_test: 1-2 short sentences (max 40 words) -- the concrete data, instrument, experiment, simulation or model\n"
    "    prediction: one short sentence (max 30 words) -- what result would support it and what would refute it\n"
    "    field: exactly one of " + ", ".join(FIELDS) + "\n"
    "    Make them specific and scientifically sound; at least one should be doable by a student (e.g. with public data or ML).\n"
    "  observation: array of exactly 6 objects, one per method in this order: " + ", ".join(OBS_METHODS) + ". "
    "Each {method, applies, how, instrument, organization, url}:\n"
    "    applies: true if this method genuinely helps study the natural phenomenon behind the verse's imagery, else false\n"
    "    how: 1-2 sentences on how the method would study it, or why it does not apply\n"
    "    instrument: a real official instrument, survey, mission or facility. For flashes, bursts, explosions and other "
    "high-energy or short-lived sky events prefer Einstein Probe (CAS/ESA), SVOM (CNSA/CNES), Insight-HXMT, NASA Fermi and "
    "Swift, ISRO AstroSat CZTI, and the LIGO, Virgo and KAGRA gravitational-wave detectors. For other sky phenomena prefer ISRO AstroSat, "
    "NCRA GMRT, SKA, NRAO VLA, ALMA, SDSS, Gaia, JWST, Hubble, Planck, Rubin Observatory LSST. For Earth, weather or "
    "living-world phenomena use real Earth-observation or field instruments (weather radar, INSAT-3D, Oceansat, GPM, "
    "NOAA, ECMWF) and NEVER an astronomical telescope: GMRT, SKA, VLA, ALMA, Hubble, JWST, Gaia, SDSS, Planck and AstroSat "
    "observe the sky and must not be named for rain, clouds, weather, oceans, land, plants or animals (for radar or radio "
    "measurements of weather name a weather radar such as ISRO DWR or NOAA NEXRAD). Set applies false when the method has no "
    "genuine use.\n"
    "    organization: who runs it; url: its official page only if you are confident it exists, else ''\n"
    "    Radio spectral imaging = mapping the sky at radio frequencies and how intensity changes across frequency. "
    "Photometry = measuring brightness through filters over time or colour. Cosmology = the origin, structure and "
    "evolution of the universe. Beta scaling = a power law in which flux or brightness scales as frequency or "
    "wavelength to the power beta, e.g. the radio spectral index of synchrotron emission (about -0.7), the dust "
    "emissivity index (about 1.5 to 2) or the ultraviolet slope beta of galaxies. Petascale data = petabyte datasets "
    "and petaflop computing, as in SKA, Rubin LSST or climate reanalysis. Visualisation = the clearest way to show the "
    "phenomenon (sky map, light curve, spectrum, simulation) and the official tool or dataset that provides it."
)


def url_ok(u):
    """Open the link once; keep it only if the page really exists (drops invented or dead links)."""
    if not re.fullmatch(r"https://[^\s\"'<>]{4,300}", u or ""):
        return False
    try:
        r = subprocess.run(["curl", "-sL", "-o", os.devnull, "-w", "%{http_code}", "-m", "8", "-r", "0-0",
                            "-A", "Mozilla/5.0 (KuralAstro link check)", u], capture_output=True, text=True, timeout=12)
        return 200 <= int(r.stdout.strip() or 0) < 400
    except (ValueError, subprocess.SubprocessError, OSError):
        return False


def finalize_deep(d):
    """Normalise real-world examples: known field, verified link, top organisations first, then newest first."""
    items = [r for r in (d.get("real_world") or []) if isinstance(r, dict) and r.get("title")]
    with ThreadPoolExecutor(6) as ex:
        oks = list(ex.map(url_ok, [r.get("url", "") for r in items]))
    for r, ok in zip(items, oks):
        r["url"] = r.get("url", "") if ok else ""
        r["field"] = r.get("field") if r.get("field") in FIELDS else "General"
        r["org_type"] = str(r.get("org_type") or "other").lower()
        r["credible"] = CREDIBLE.get(r["org_type"], 3) <= 1
        m = re.search(r"\d{4}", str(r.get("year") or ""))
        r["year"] = int(m.group()) if m else 0
    items.sort(key=lambda r: (CREDIBLE.get(r["org_type"], 3), -r["year"]))
    d["real_world"] = items
    kinds = ("testable hypothesis", "theoretical idea", "application idea")
    hyps = [h for h in (d.get("hypotheses") or []) if isinstance(h, dict) and h.get("statement")]
    for h in hyps:
        h["kind"] = h.get("kind") if h.get("kind") in kinds else "theoretical idea"
        h["field"] = h.get("field") if h.get("field") in FIELDS else "General"
    d["hypotheses"] = hyps[:3]
    # match the model's method names loosely ("Radio Spectral Imaging", "Petascale Data Handling", ...)
    keys = {"radio": 0, "photometr": 1, "cosmolog": 2, "beta": 3, "peta": 4, "visuali": 5}
    obs = {}
    for o in (d.get("observation") or []):
        name = str(o.get("method", "")).lower() if isinstance(o, dict) else ""
        hit = next((i for k, i in keys.items() if k in name), None)
        if hit is not None and hit not in obs:
            obs[hit] = o
    rows = [{**obs.get(i, {}), "method": m} for i, m in enumerate(OBS_METHODS)]
    with ThreadPoolExecutor(6) as ex:
        oks = list(ex.map(url_ok, [o.get("url", "") for o in rows]))
    for o, ok in zip(rows, oks):
        o["applies"] = bool(o.get("applies"))
        o["url"] = o.get("url", "") if ok else ""
        for k in ("how", "instrument", "organization"):
            o[k] = str(o.get(k) or "")[:400]
    d["observation"] = rows
    return d


COLLECTION_SYS = (
    "You are a research assistant for a student project comparing classical Tamil verses (Thirukkural, Thiruvarutpa) "
    "with modern science. Below are the leaves (verses) the student saved, each with its AI reading and the student's own "
    "note, plus the REAL-WORLD science attached to it (missions, experiments, observations) and research papers. Analyse the "
    "leaves TOGETHER and focus on the science: compare the real-world sources behind each leaf, find where leaves point to "
    "the same science, and judge how well each verse's imagery actually matches that science. Be honest: these are "
    "analogies, not evidence the poets knew modern science.\n"
    "Return JSON with keys:\n"
    "  overview: 3-4 sentences on what this collection is about and the science it touches\n"
    "  science: array of 2-5 {topic, leaves: [ids], real_world, match} -- group leaves by the science they point to; "
    "real_world = which missions/experiments/papers from their sources show this science; "
    "match = how closely the verses' imagery fits that science and where it breaks down\n"
    "  connections: array of up to 6 {leaves: [id, id], relation, basis, how} -- links between specific leaves. "
    "basis: one of 'same imagery', 'same scientific concept', 'shared real-world source', 'contrasting views'. "
    "how: one sentence on exactly what you compared to find this link (which ideas, images or sources)\n"
    "  analysis: one or two paragraphs -- your overall analysis of the collection: patterns, strongest and weakest links to real science, what it all adds up to\n"
    "  conclusions: array of 3-5 short, defensible conclusions the student could put in a report\n"
    "  next_topics: array of 3-5 short ENGLISH science topics worth searching next\n"
    "Refer to leaves only by the ids given. Use the student's notes where relevant."
)


def analyse_collection(user, lang, fresh=False):
    items = library.list_items(user)[:40]
    if len(items) < 2:
        return None, "Save at least 2 leaves to analyse them together."
    brief = [{"id": i["id"], "source": i["verse"].get("source") or "user verse", "ref": i["verse"].get("ref", ""),
              "label": i["verse"].get("label", ""), "concept": i["verse"].get("concept", ""),
              "tamil": i["verse"].get("tamil", "")[:200], "meaning": i["verse"].get("meaning", ""),
              "literal": (i.get("deep") or {}).get("literal", "")[:300], "analogy": (i.get("deep") or {}).get("analogy", "")[:300],
              "note": i.get("note", "")[:300],
              "real_world": [f"{r.get('organization') or ''} | {r.get('title', '')}: {r.get('detail', '')[:160]}"
                             for r in (i.get("deep") or {}).get("real_world", [])][:5],
              "papers": [f"{p.get('title', '')} ({p.get('year', '')})" for p in i.get("papers", [])][:5]} for i in items]
    key = ckey("collection-v3", user, lang, json.dumps(brief, ensure_ascii=False, sort_keys=True))
    def run():
        prompt = COLLECTION_SYS + LANG_NOTE[lang] + "\n\nLeaves:\n" + json.dumps(brief, ensure_ascii=False)
        d = gemini_json(prompt, attempts=4)
        return d if isinstance(d, dict) and d.get("overview") else None
    report = cached(key, None, run, fresh=fresh)
    if not report:
        return None, "The AI service is busy. Try again in a few seconds."
    ids = {i["id"] for i in items}
    for t in report.get("science") or []:
        t["leaves"] = [x for x in (t.get("leaves") or []) if x in ids]
    report["connections"] = [c for c in (report.get("connections") or []) if len(c.get("leaves") or []) >= 2 and all(x in ids for x in c["leaves"][:2])]
    by_id = {i["id"]: i for i in items}
    for c in report["connections"]:
        c["metrics"] = pair_metrics(by_id[c["leaves"][0]], by_id[c["leaves"][1]])
    names = {i["id"]: {"ref": i["verse"].get("ref") or "Your verse", "source": i["verse"].get("source", "")} for i in items}
    return {"report": report, "leaves": names, "count": len(items), "shared": shared_sources(items),
            "without_sources": [i["id"] for i in items if not i.get("papers") and not (i.get("deep") or {}).get("real_world")]}, None


TA_WORD = re.compile(r"[\u0B80-\u0BFF]+")


def pair_metrics(a, b):
    """Transparent, non-AI measures for a pair of leaves: shared Tamil words (lexical) and shared sources (exact)."""
    wa = {w for w in TA_WORD.findall(a["verse"].get("tamil", "")) if len(w) > 2}
    wb = {w for w in TA_WORD.findall(b["verse"].get("tamil", "")) if len(w) > 2}
    shared = sorted(wa & wb, key=len, reverse=True)
    overlap = round(100 * len(wa & wb) / len(wa | wb)) if wa | wb else 0
    src = lambda i: ({p.get("url") for p in i.get("papers", [])} |
                     {re.sub(r"[^a-z0-9]+", " ", (r.get("title") or "").lower()).strip() for r in (i.get("deep") or {}).get("real_world", [])})
    return {"word_overlap": overlap, "shared_words": shared[:5], "shared_sources": len((src(a) & src(b)) - {"", None})}


def shared_sources(items):
    """Papers and real-world examples that appear under more than one saved leaf (exact matches, no AI)."""
    seen = {}
    for i in items:
        for p in i.get("papers", []):
            k = ("paper", p.get("url"))
            seen.setdefault(k, {"kind": "paper", "title": p.get("title"), "url": p.get("url"), "year": p.get("year"), "leaves": []})
            seen[k]["leaves"].append(i["id"])
        for r in (i.get("deep") or {}).get("real_world", []):
            k = ("real", re.sub(r"[^a-z0-9]+", " ", (r.get("title") or "").lower()).strip())
            seen.setdefault(k, {"kind": "real", "title": r.get("title"), "leaves": []})
            seen[k]["leaves"].append(i["id"])
    shared = [s for s in seen.values() if len(set(s["leaves"])) > 1]
    for s in shared:
        s["leaves"] = sorted(set(s["leaves"]))
    return sorted(shared, key=lambda s: -len(s["leaves"]))[:12]


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
            now = time.time()
            _health_hits[:] = [t for t in _health_hits if now - t < 600] + [now]
            return self._json(200, {"ok": True, "awake_minutes": round((now - STARTED) / 60, 1),
                                    "pings_last_10_min": len(_health_hits)})
        if path == "/api/config":
            return self._json(200, {"invite_required": bool(os.environ.get("INVITE_CODE"))})
        if path in ("/login", "/login.html"):
            return self._redirect("/") if self._user() else self._static("login.html")
        if re.fullmatch(r"/s/[A-Za-z0-9_-]{6,16}", path):
            return self._static("share.html")
        m = re.fullmatch(r"/api/share/([A-Za-z0-9_-]{6,16})", path)
        if m:
            item = STORE.share_get(m.group(1))
            return self._json(200, item) if item else self._json(404, {"error": "This shared leaf does not exist."})
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
            counts = {k: {"title": rr.TOPICS[k][0], "count": 0} for k in rr.ASTRO_THEMES}
            for v in verse_list():
                if v["astro"]:
                    counts[v["theme"]]["count"] += 1
            return self._json(200, counts)
        if path == "/api/concepts":
            lang = (parse_qs(url.query).get("lang") or ["en"])[0]
            return self._json(200, concept_translations(lang))
        if path == "/api/images":
            q = (parse_qs(url.query).get("q") or [""])[0].strip()[:120]
            if not q:
                return self._json(400, {"error": "empty q"})
            imgs = cached(ckey("nasa-img-v2", q.lower()), 7 * DAY, lambda: {
                "general": osrc.nasa_images_best(q, 6), "radio": osrc.nasa_images(" ".join(q.split()[:2]) + " radio", 3)})
            return self._json(200, imgs or {"general": [], "radio": []})
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
        lang = "ta" if body.get("lang") == "ta" else "en"
        if path == "/api/saved/analyze":
            out, err = analyse_collection(user, lang, bool(body.get("fresh")))
            return self._json(400 if err and "Save at least" in err else 502, {"error": err}) if err else self._json(200, out)
        if path == "/api/share":
            item = library._clean(body)
            if not item:
                return self._json(400, {"error": "Nothing to share."})
            item.pop("note", None)  # notes are private
            item["shared_by"] = user
            sid = secrets.token_urlsafe(6)
            STORE.share_put(sid, user, item)
            return self._json(200, {"id": sid, "url": f"/s/{sid}"})
        if path == "/api/search_topic":
            topic = (body.get("topic") or "").strip()[:200]
            if not topic:
                return self._json(400, {"error": "empty topic"})
            res = search_by_topic(topic, body.get("key"), lang)
            if res is None:
                return self._json(502, {"error": "The AI service is busy. Try again in a few seconds."})
            return self._json(200, res)
        if path == "/api/analyze":
            text = (body.get("text") or "").strip()
            if not text:
                return self._json(400, {"error": "empty text"})
            verse = json.dumps({"id": "adhoc", "text": text[:1500]}, ensure_ascii=False)

            def label_it():
                res = gemini_json(f"{g.SYSTEM}\n\nVerses:\n{verse}", attempts=4, temperature=0)
                res = [res] if isinstance(res, dict) else res
                return res[0] if res and isinstance(res[0], dict) and res[0].get("label") else None
            r = cached(ckey("analyze", text[:1500]), None, label_it)
            if not r:
                return self._json(502, {"error": "The AI service is busy. Try again in a few seconds."})
            topic_title, papers = None, []
            if r.get("label") in ("L", "O", "A") and r.get("science_concept"):
                topic_title, papers = papers_for(r["science_concept"])
            return self._json(200, {**r, "topic_title": topic_title, "papers": papers})
        if path == "/api/deep":
            text, concept = (body.get("text") or "").strip()[:2000], (body.get("concept") or "").strip()[:200]
            if not text:
                return self._json(400, {"error": "empty text"})
            def read_it():
                for _ in range(2):   # retry once if the model skipped the observational lens
                    d = gemini_json(f"{DEEP_SYS}{LANG_NOTE[lang]}\n\nVerse: {text}\nModern concept: {concept or '(none identified)'}")
                    if not (isinstance(d, dict) and d.get("literal")):
                        return None
                    d = finalize_deep(d)
                    if sum(1 for o in d["observation"] if o["how"]) >= 3:
                        break
                return d
            out = cached(ckey("deep-v9", lang, text, concept), None, read_it, fresh=bool(body.get("fresh")))
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
