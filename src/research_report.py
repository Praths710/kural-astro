"""Link verse science-concepts to real papers on arXiv and write reports/verse_science_report.md.

Papers come from live arXiv search (keyless API); nothing is generated from memory. The
concept->topic map below is transparent and hand-written: a topic is an ANALOGY target, chosen
so a reviewer can accept or reject it. Input is the label files (later: the LLM's predictions).
"""
import csv
import json
import subprocess
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "processed" / "arxiv_cache.json"
REPORT = ROOT / "reports" / "verse_science_report.md"
NS = {"a": "http://www.w3.org/2005/Atom"}

# topic -> (title, trigger substrings in the verse's concept text, arXiv queries)
TOPICS = {
    "holographic": ("Holographic principle / information in bounded regions",
        ["atom", "macro-in-micro", "macrocosm", "microcosm", "small point", "contained within",
         "enclosed", "fraction of an atom", "dust of an atom", "subatomic"],
        ['all:"holographic principle"']),
    "multiverse": ("Multiverse / many-universe cosmology",
        ["universe", "multiverse", "cosmoses", "nested", "worlds within worlds", "cosmic realms",
         "cosmic worlds", "many worlds", "cosmic eggs", "cosmic generation"],
        ['all:multiverse AND all:cosmology']),
    "extra_dim": ("Extra dimensions / nested spaces (braneworld, Kaluza-Klein)",
        ["space", "dimension", "layered", "transcendental", "paramakasa"],
        ['all:"extra dimensions" AND all:braneworld', 'all:"Kaluza-Klein"']),
    "light_medium": ("Light pervading the universe (CMB / background radiation)",
        ["light pervad", "light fill", "cosmic light", "radiant light", "light extending",
         "self-luminous", "draw their light", "all radiance", "single light", "light (kadir", "illumination"],
        ['all:"cosmic microwave background"', 'all:"extragalactic background light"']),
    "dissolution": ("Cosmic end-states (heat death, big crunch)",
        ["dissolve", "dissolution", "collapse", "fall apart"],
        ['all:"heat death" AND all:universe', 'all:"big crunch"']),
    "no_centre": ("Homogeneity and isotropy (no preferred centre or direction)",
        ["no up/down", "dimensionless", "no beginning", "centre", "center", "immobile center"],
        ['all:"cosmological principle" AND all:isotropy']),
    "cosmogony": ("Cosmic evolution from a primordial state (Big Bang nucleosynthesis)",
        ["cosmogony", "element order", "cosmic evolution", "tattva", "primal principle",
         "five elements", "elemental structure", "cosmic ordering"],
        ['all:"Big Bang nucleosynthesis"']),
    "lunar": ("Lunar phases and surface features (orbital mechanics, maria formation)",
        ["lunar", "moon", "stellar", "moonlight"],
        ['all:"lunar maria" AND all:origin', 'all:"lunar phases"']),
    "eclipse": ("Eclipse mechanics (orbital alignment)",
        ["eclipse"],
        ['all:"solar eclipse" AND all:mechanism', 'all:"lunar eclipse" AND all:geometry']),
    "solar_motion": ("Apparent solar motion (Earth's rotation, diurnal cycle)",
        ["apparent movement of the sun", "solar heat", "sunlight", "sun blocking"],
        ['all:"diurnal motion" AND all:sun', 'all:"apparent motion" AND all:sun AND all:earth']),
    "monsoon": ("Monsoon dynamics and the water cycle",
        ["rain", "water cycle", "monsoon", "famine", "hydrology", "groundwater", "drought"],
        ['all:"Indian summer monsoon" AND all:variability', 'all:"hydrological cycle"']),
}


def arxiv(query, sort):
    cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
    key = f"{query}|{sort}"
    if key in cache:
        return cache[key]
    time.sleep(3)
    url = "https://export.arxiv.org/api/query?" + urllib.parse.urlencode(
        {"search_query": query, "max_results": 3, "sortBy": sort, "sortOrder": "descending"})
    # arXiv answers 406 to Python's HTTP client but not to curl, so fetch via curl.
    raw = subprocess.run(["curl", "-s", "-m", "60", "-A", "kural-astro-student-project/0.1", url],
                         capture_output=True, check=True).stdout
    root = ET.fromstring(raw)
    out = []
    for e in root.findall("a:entry", NS):
        out.append({
            "title": " ".join(e.find("a:title", NS).text.split()),
            "year": e.find("a:published", NS).text[:4],
            "authors": [a.find("a:name", NS).text for a in e.findall("a:author", NS)][:3],
            "url": e.find("a:id", NS).text.replace("http://", "https://"),
        })
    cache[key] = out
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


def load_verses():
    """Prefer Gemini-labeled verses (larger, less biased); fall back to my hand-labels
    for anything Gemini didn't cover (e.g. it only ran on the keyword-candidate set)."""
    rows, seen = [], set()
    gem_path = ROOT / "data/labels/gemini_labels_dedup.json"
    if gem_path.exists():
        gem = json.loads(gem_path.read_text(encoding="utf-8"))
        kurals = {k["Number"]: k for k in json.loads((ROOT / "data/raw/thirukkural.json").read_text(encoding="utf-8"))["kural"]}
        arutpa = {(r["section_id"], r["stanza_no"]): r for r in
                  (json.loads(l) for l in (ROOT / "data/processed/thiruvarutpa.jsonl").read_text(encoding="utf-8").splitlines())}
        for vid, r in gem.items():
            if r["label"] not in ("L", "O", "A") or not r.get("science_concept"):
                continue
            kind, *rest = vid.split(":")
            if kind == "kural":
                k = kurals.get(int(rest[0]))
                if not k:
                    continue
                ref, text = f"Thirukkural {rest[0]}", f"{k['Line1']} {k['Line2']}"
            else:
                sec, stanza = rest
                v = arutpa.get((sec, stanza))
                if not v:
                    continue
                ref, text = f"Thiruvarutpa {v['section_title']} st.{stanza}", v["text"]
            rows.append({"ref": ref, "text": text, "label": r["label"], "concept": r["science_concept"]})
            seen.add(vid)

    for path, src in (("data/labels/silver_labels.csv", "kural"), ("data/labels/arutpa_silver_labels.csv", "arutpa"),
                      ("data/labels/arutpa_silver_round2.csv", "arutpa")):
        for r in csv.DictReader((ROOT / path).open(encoding="utf-8-sig")):
            key = f"kural:{r['number']}" if src == "kural" else f"arutpa:{r['section_id']}:{r['stanza_no']}"
            if key in seen:
                continue
            concept = r.get("science_concept") or (r.get("notes", "").split("; ", 1)[-1] if r["label"] == "A" else "")
            if r["label"] in ("L", "O", "A") and concept:
                if src == "kural":
                    ref, text = f"Thirukkural {r['number']}", r["tamil"]
                else:
                    ref, text = f"Thiruvarutpa {r['section_title']} st.{r['stanza_no']}", r["text"]
                rows.append({"ref": ref, "text": text, "label": r["label"], "concept": concept})
    return rows


def main():
    verses = load_verses()
    by_topic = {k: [] for k in TOPICS}
    unmapped = []
    for v in verses:
        hit = [k for k, (_, trig, _) in TOPICS.items() if any(t in v["concept"].lower() for t in trig)]
        for k in hit:
            by_topic[k].append(v)
        if not hit:
            unmapped.append(v)

    lines = ["# Verse -> modern science: candidate analogies with real papers", "",
             "Verses and labels are provisional (silver, unverified). Each topic is an analogy target, not a claim",
             "that the poet knew the science. Papers are live arXiv search results (foundational = most relevant,",
             "recent = newest submissions); read them before citing.", ""]
    for k, (title, _, queries) in TOPICS.items():
        vs = by_topic[k]
        if not vs:
            continue
        lines += [f"## {title}", f"*{len(vs)} verse(s) mapped*", ""]
        for v in vs[:8]:
            lines.append(f"- **{v['ref']}** [{v['label']}] — {v['concept']}  \n  `{v['text'][:110]}`")
        if len(vs) > 8:
            lines.append(f"- ...and {len(vs) - 8} more")
        lines += ["", "**Papers**", ""]
        seen = set()
        for q in queries:
            for tag, sort in (("foundational", "relevance"), ("recent", "submittedDate")):
                for p in arxiv(q, sort):
                    if p["url"] in seen:
                        continue
                    seen.add(p["url"])
                    lines.append(f"- ({tag}, {p['year']}) [{p['title']}]({p['url']}) — {', '.join(p['authors'])}")
        lines.append("")
    lines += ["## Verses with no automatic topic", ""]
    lines += [f"- {v['ref']} [{v['label']}] — {v['concept']}" for v in unmapped[:40]]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print(f"{len(verses)} verses with concepts; mapped {len(verses) - len(unmapped)}, unmapped {len(unmapped)}")
    print({k: len(v) for k, v in by_topic.items()})
    print("wrote", REPORT)


if __name__ == "__main__":
    main()
