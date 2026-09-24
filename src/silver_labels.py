"""Provisional (silver) labels for keyword candidates, assigned by Claude by reading each
verse + translation. NOT ground truth: a human must verify (see reports/label_review.md).

L = verse directly states a natural/physical fact
O = verse encodes a real observation inside a simile/analogy
A = ambiguous: astrology, myth, or folk-causal belief
M = natural imagery used purely as a figure of speech
N = spurious keyword match (word means something else, e.g. தீ = evil)
"""
import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CAND = ROOT / "data" / "processed" / "candidates.csv"
OUT = ROOT / "data" / "labels" / "silver_labels.csv"

L = {
    11: "water cycle: rain sustains life",
    12: "rain -> agriculture/food chain",
    13: "monsoon failure -> famine",
    14: "rain-fed agriculture",
    15: "rain as both destructive (flood) and restorative",
    16: "rain and vegetation",
    17: "ocean-cloud water cycle (evaporation/precipitation)",
    18: "dependence of ritual/agrarian life on rain",
    19: "dependence of civilisation on rain",
    20: "water originates from rain",
    737: "terrain/hydrology: rivers, hills as features of a habitable land",
}
O = {
    77: "solar heat desiccates organisms",
    267: "heating purifies metal (metallurgy)",
    396: "water table depth vs digging depth",
    452: "soil composition changes water chemistry/taste",
    481: "diurnal vs nocturnal predator advantage (owl/crow)",
    495: "habitat-dependent animal advantage (crocodile in water)",
    496: "medium-dependent vehicles (ship vs chariot)",
    595: "water depth vs lotus stem length",
    742: "hydrology/terrain used in fort design",
    782: "lunar phases (waxing/waning)",
    957: "lunar surface features (maculae)",
    1037: "soil drying/tilling and crop yield",
    1117: "lunar phases and spots",
}
A = {
    1: "cosmogony: primal principle as origin of the world",
    211: "rain as unrequited benefactor (folk-moral)",
    371: "astrological belief: fortune tied to a waxing/waning star",
    542: "earth depends on sky/rain, mapped onto king-subject relation",
    545: "folk-causal: righteous rule -> rain and yield",
    557: "folk-causal: unjust king -> rainless earth",
    559: "folk-causal: unjust king -> sky withholds seasonal rain",
    610: "mythic cosmology: Vishnu spanning three worlds (commentary note)",
}
M = {
    8, 10, 103, 124, 129, 202, 215, 298, 299, 306, 308, 313, 324, 390, 435, 487, 556, 601,
    622, 653, 660, 674, 691, 698, 718, 753, 763, 764, 870, 881, 896, 898, 899, 929, 969,
    970, 971, 989, 999, 1010, 1049, 1093, 1104, 1116, 1118, 1119, 1134, 1137, 1146, 1147,
    1148, 1159, 1160, 1164, 1166, 1167, 1170, 1175, 1186, 1192, 1200, 1210, 1228, 1239,
    1260, 1309, 1323,
}


def main():
    rows = list(csv.DictReader(CAND.open(encoding="utf-8-sig")))
    counts = {}
    for r in rows:
        n = int(r["number"])
        if n in L:
            lab, why = "L", L[n]
        elif n in O:
            lab, why = "O", O[n]
        elif n in A:
            lab, why = "A", A[n]
        elif n in M:
            lab, why = "M", ""
        else:
            lab, why = "N", ""
        r["label"], r["science_concept"] = lab, why
        r["notes"] = "silver-unverified"
        counts[lab] = counts.get(lab, 0) + 1
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(counts, "total", len(rows))
    print("wrote", OUT)


if __name__ == "__main__":
    main()
