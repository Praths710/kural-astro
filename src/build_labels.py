"""Rebuild data/labels/gemini_labels_dedup.json (what the app reads) from the labelling log.

The log (gemini_labels.jsonl) is append-only and may hold a verse more than once or a PARSE_ERROR row;
the latest valid label per verse wins.
"""
import collections
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG, OUT = ROOT / "data/labels/gemini_labels.jsonl", ROOT / "data/labels/gemini_labels_dedup.json"

best = {}
for line in LOG.read_text(encoding="utf-8").splitlines():
    try:
        r = json.loads(line)
    except json.JSONDecodeError:
        continue
    if r.get("id") and r.get("label") in ("L", "O", "A", "M", "N"):
        best[r["id"]] = {"id": r["id"], "label": r["label"], "science_concept": r.get("science_concept", ""),
                         "meaning": r.get("meaning", "")}
OUT.write_text(json.dumps(best, ensure_ascii=False, indent=0), encoding="utf-8")
by_src = collections.Counter(k.split(":")[0] for k in best)
labels = collections.Counter((k.split(":")[0], v["label"]) for k, v in best.items())
print(len(best), "labelled", dict(by_src))
print("science (A/O/L) per text:", {s: sum(labels[(s, l)] for l in "AOL") for s in by_src})
