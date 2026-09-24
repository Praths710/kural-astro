"""Pass 1: keyword candidate retrieval over the Thirukkural corpus (stdlib only).

A kural becomes a candidate only if it has a STRONG hit (non-polysemous stem) in the
verse itself or its English rendering. Polysemous (weak) and commentary-only hits are
recorded as supporting context. Output has blank label columns for manual review.
Labels: L = literal natural/celestial reference, M = metaphor only, A = ambiguous, N = none.
"""
import csv
import json
import re
from pathlib import Path

from lexicon import LEXICON

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "raw" / "thirukkural.json"
OUT = ROOT / "data" / "processed" / "candidates.csv"

VERSE_FIELDS = ["Line1", "Line2"]
EN_FIELDS = ["Translation", "couplet", "explanation"]
COMMENTARY_FIELDS = ["mv", "sp", "mk"]

TAMIL_START = "(?<![஀-௿])"


def ta_hit(stem, text):
    return re.search(TAMIL_START + re.escape(stem), text) is not None


def scan(kural):
    verse = " ".join(kural.get(f, "") for f in VERSE_FIELDS)
    comm = " ".join(kural.get(f, "") for f in COMMENTARY_FIELDS)
    en = " ".join(kural.get(f, "") for f in EN_FIELDS).lower()
    strong, weak, support = {}, {}, {}
    for cat, spec in LEXICON.items():
        for stem in spec["ta"]:
            is_weak = stem in spec["poly"]
            if ta_hit(stem, verse):
                (weak if is_weak else strong).setdefault(cat, []).append(stem + "*")
            elif ta_hit(stem, comm):
                support.setdefault(cat, []).append(stem)
        for pat in spec["en"]:
            if re.search(pat, en):
                strong.setdefault(cat, []).append(pat.replace(r"\b", ""))
    return strong, weak, support


def main():
    kurals = json.loads(SRC.read_text(encoding="utf-8"))["kural"]
    rows = []
    for k in kurals:
        strong, weak, support = scan(k)
        if not strong:
            continue
        rows.append({
            "number": k["Number"],
            "chapter": (k["Number"] - 1) // 10 + 1,
            "categories": "|".join(strong),
            "strong_terms": " ; ".join(f"{c}:{','.join(t)}" for c, t in strong.items()),
            "weak_terms_in_verse": " ; ".join(f"{c}:{','.join(t)}" for c, t in weak.items()),
            "commentary_only_terms": " ; ".join(f"{c}:{','.join(t)}" for c, t in support.items()),
            "n_categories": len(strong),
            "tamil": f"{k['Line1']} / {k['Line2']}",
            "translation": k["Translation"],
            "explanation": k["explanation"],
            "commentary_mv": k["mv"],
            "commentary_mk": k["mk"],
            "label": "",
            "science_concept": "",
            "notes": "",
        })
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    per_cat = {}
    for r in rows:
        for c in r["categories"].split("|"):
            per_cat[c] = per_cat.get(c, 0) + 1
    print(f"{len(rows)} candidates of {len(kurals)} kurals ({len(rows)/len(kurals):.0%})")
    for c, n in sorted(per_cat.items(), key=lambda x: -x[1]):
        print(f"  {c:18s} {n}")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
