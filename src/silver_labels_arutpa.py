"""Provisional (silver) labels for Thiruvarutpa keyword candidates, assigned by Claude from
keyword-in-context windows (reports/arutpa_kwic.txt). NOT ground truth: verify with a Tamil reader.
Indices refer to row order in data/processed/arutpa_candidates.csv.

A = mystical-cosmological statement with scale/structure content (many/nested universes, atom
    containing universes, layered spaces, light pervading universes, element cosmogony)
O = poetic observation of a natural phenomenon
M = devotional metaphor / formulaic phrase / iconography (default)
N = spurious match (word means something else, e.g. அண்டர் 'gods', editorial notes)
"""
import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CAND = ROOT / "data" / "processed" / "arutpa_candidates.csv"
OUT = ROOT / "data" / "labels" / "arutpa_silver_labels.csv"

A = {
    3, 4, 15, 16, 17, 21, 23, 25, 26, 30, 31, 33, 47, 52, 55, 73, 87, 88, 107, 108, 120, 121,
    123, 125, 127, 128, 129, 137, 138, 140, 142, 144, 148, 154, 155, 156, 158, 159, 160, 161,
    162, 164, 165, 166, 168, 169, 170, 176, 189, 192, 193, 195, 197, 201, 204, 207, 209, 210,
    232, 234, 239, 241, 249,
}
O = {
    28: "moonlight described as cool rays",
    53: "sun's daily course; each day follows and ends behind it",
    111: "darkness cannot engulf the sun (light vs dark)",
}
N = {
    0, 1, 2, 11, 12, 13, 20, 36, 37, 38, 40, 44, 45, 46, 48, 49, 51, 54, 57, 61, 62, 63, 72,
    79, 81, 102, 103, 105, 110, 113, 114, 119, 131, 135, 146, 147, 225, 227, 235, 243, 244, 245,
}
CONCEPT = {
    4: "macro-in-micro: all universes enclosed within an atom",
    17: "scale: entity that was atom-sized extends across the eight directions",
    33: "layered/stacked universes",
    137: "universe above universe (nested cosmoses)",
    138: "traversing crores of universes in half a moment",
    140: "light (kadir-oli) pervading all of space",
    142: "the small/large: present where even an atom cannot go",
    148: "nested light/space hierarchy beyond ordinary space",
    155: "hierarchy of universes",
    158: "radiating light sustains the worlds/universes",
    168: "all radiance contained in an atom; no up/down/centre (dimensionless)",
    169: "all layered universes fit in one-crore-th of a fraction of an atom",
    170: "beings of crores of universes",
    189: "layered 'spaces': element-space, instrument-space, higher spaces",
    192: "elements arise from a subtle atomic power (vaal-anu)",
    193: "atom-within-atom, light within light",
    195: "single light pervades all universes",
    197: "nested spaces: space of spaces beyond spaces",
    204: "cosmic evolution: unity -> duality -> ego categories (tattva cosmogony)",
    210: "the light from which sun and moon draw their light",
    232: "many universes within the dust of an atom",
    234: "all universes contained in an atom",
    241: "a still greater space exists beyond this one",
    87: "self-luminous light that shines where sun and moon do not appear",
    123: "light filling countless universes",
    128: "element order: space -> air -> fire",
    88: "all cosmic and bodily kinds arise and dissolve",
    52: "even if all universes collapse and dissolve",
}


def main():
    rows = list(csv.DictReader(CAND.open(encoding="utf-8-sig")))
    counts = {}
    for i, r in enumerate(rows):
        if i in A:
            lab, why = "A", CONCEPT.get(i, "mystic-cosmological statement (unverified)")
        elif i in O:
            lab, why = "O", O[i]
        elif i in N:
            lab, why = "N", ""
        else:
            lab, why = "M", ""
        r["label"], r["science_concept"], r["notes"] = lab, why, "silver-unverified"
        counts[lab] = counts.get(lab, 0) + 1
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(counts, "total", len(rows))


if __name__ == "__main__":
    main()
