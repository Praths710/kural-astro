"""Keyword candidate retrieval over Thiruvarutpa stanzas (Tamil only; no English rendering scraped).

Writes data/processed/arutpa_candidates.csv with blank label columns.
Labels: L literal cosmic/physical statement, O observation/analogy with physical content,
A ambiguous/mystical-cosmological, M light/fire etc. as pure devotional metaphor, N spurious.
Cosmic-scale terms (அண்டம், ஆகாயம், பிண்டம்...) are 'strong'; generic light words are 'weak'
because Vallalar uses ஒளி/சோதி/சுடர் for the Divine in nearly every hymn.
"""
import csv
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "processed" / "thiruvarutpa.jsonl"
OUT = ROOT / "data" / "processed" / "arutpa_candidates_v2.csv"

START = "(?<![஀-௿])"

STRONG = {
    "cosmos": ["அண்டம்", "அண்டங்க", "அண்ட", "பிண்டம்", "பிரபஞ்ச", "உலகங்கள்", "புவனம்", "புவனங்க"],
    "space_elements": ["ஆகாயம்", "வான்வெளி", "அருள்வெளி", "பெருவெளி", "=வெளி", "பரவெளி", "நடுவெளி", "பாழ்வெளி", "பூதவெளி", "துரியவெளி", "சுகவெளி", "கருவெளி", "உருவெளி", "மௌனவெளி", "சிற்பரவெளி", "ஏழ்வெளி", "வெளிகள்", "வெளிகளெல", "பஞ்சபூத", "ஐம்பூத", "பூதங்கள்", "காற்று", "வாயு"],
    "sun_moon_stars": ["சூரிய", "சந்திர", "ஞாயிறு", "திங்கள்", "கதிரவ", "நிலவு", "நட்சத்திர", "விண்மீன்", "கோள்கள்", "கிரக"],
    "light_physics": ["கிரண", "கதிர்", "ஒளிக்கதிர்", "கதிரொளி", "மின்னல்", "=மின்"],
    "vibration_sound": ["நாதம்", "அதிர்வு", "அதிர்"],
    "time_scale": ["யுகம்", "கற்பம்"],
    "atom_smallest": ["=அணு", "அணுவ", "அணுத்துணை", "நுண்ணணு"],
}
WEAK = {
    "light_generic": ["ஒளி", "சோதி", "ஜோதி", "சுடர்", "பிரகாச", "விளக்க", "தீபம்", "தேஜ"],
}


def hits(text, table):
    out = {}
    for cat, stems in table.items():
        for s in stems:
            whole = s.startswith("=")
            pat = START + re.escape(s.lstrip("=")) + ("(?![஀-௿])" if whole else "")
            if re.search(pat, text):
                out.setdefault(cat, []).append(s)
    return out


def main():
    rows = [json.loads(l) for l in SRC.read_text(encoding="utf-8").splitlines()]
    out = []
    for r in rows:
        strong = hits(r["text"], STRONG)
        if not strong:
            continue
        weak = hits(r["text"], WEAK)
        out.append({
            "volume": r["volume"], "section_id": r["section_id"],
            "section_title": r["section_title"], "stanza_no": r["stanza_no"],
            "categories": "|".join(strong),
            "strong_terms": " ; ".join(f"{c}:{','.join(t)}" for c, t in strong.items()),
            "weak_terms": " ; ".join(f"{c}:{','.join(t)}" for c, t in weak.items()),
            "text": r["text"].replace("\n", " / "),
            "source_url": r["source_url"],
            "label": "", "science_concept": "", "notes": "",
        })
    with OUT.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]))
        w.writeheader()
        w.writerows(out)
    cats = {}
    for o in out:
        for c in o["categories"].split("|"):
            cats[c] = cats.get(c, 0) + 1
    print(f"{len(out)} candidates of {len(rows)} stanzas ({len(out)/len(rows):.0%})")
    for c, n in sorted(cats.items(), key=lambda x: -x[1]):
        print(f"  {c:16s} {n}")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
