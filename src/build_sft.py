"""Build the supervised fine-tuning set from all silver labels (Thirukkural + Thiruvarutpa).

v2 (after the first run predicted only N/M and scored 0 on A/O):
- science-type examples (L/O/A) repeated in train so they cannot be ignored
- keyword hints from the lexicon added to every prompt (same hints exist at inference time)
- Tamil text capped at 600 chars; N/M downsampled
Splits are by chapter/section (never by verse). Labels are silver (unverified).
"""
import csv
import hashlib
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import candidates as ck  # noqa: E402
import candidates_arutpa as ca  # noqa: E402

OUT = ROOT / "data" / "train"
REPEAT_POS = 5
MAX_TAMIL = 600

SYSTEM = (
    "You analyse classical Tamil verses (Thirukkural, Thiruvarutpa) for natural-science content. "
    "Labels: L literal natural fact; O real observation inside a simile; A mystic-cosmological statement "
    "(nested/many universes, universe inside an atom, layered spaces, light pervading universes; analogy only); "
    "M metaphor or devotional imagery; N no physical content. Missing a genuine L/O/A verse is worse than "
    "flagging a doubtful one. Never claim the author knew modern science; frame links as analogy."
)
LABELS = {
    "L": "literal statement of a natural phenomenon",
    "O": "real observation embedded in a simile",
    "A": "mystic-cosmological statement (analogy only)",
    "M": "metaphor or devotional imagery, no physical content",
    "N": "no physical content (keyword false positive)",
}
CAVEAT = {
    "L": "Direct natural observation; verify against modern hydrology/astronomy.",
    "O": "Observation inside a simile; the science link is the reader's inference.",
    "A": "Analogy only; not evidence that the author knew modern physics.",
    "M": "",
    "N": "",
}


def hints_arutpa(text):
    h = list(ca.hits(text, ca.STRONG))
    h += [f"weak:{c}" for c in ca.hits(text, ca.WEAK)]
    return ", ".join(h) or "none"


def hints_kural(k):
    strong, _weak, _support = ck.scan(k)
    return ", ".join(strong) or "none"


def user_prompt(src, tamil, hints, translation="", commentary=""):
    parts = [f"Source: {src}", f"Tamil: {tamil[:MAX_TAMIL]}", f"Keyword hints: {hints}"]
    if translation:
        parts.append(f"English: {translation}")
    if commentary:
        parts.append(f"Commentary: {commentary[:300]}")
    parts.append("Return JSON with keys label (L/O/A/M/N), meaning, science_concept, caveat.")
    return "\n".join(parts)


def example(src, group, tamil, label, concept, hints, translation="", commentary=""):
    resp = {"label": label, "meaning": LABELS[label],
            "science_concept": concept if label in "LOA" else "", "caveat": CAVEAT[label]}
    return group, {"messages": [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": user_prompt(src, tamil, hints, translation, commentary)},
        {"role": "assistant", "content": json.dumps(resp, ensure_ascii=False)},
    ], "label": label}


def read(p):
    return list(csv.DictReader((ROOT / p).open(encoding="utf-8-sig")))


def main():
    random.seed(7)
    ex = []
    kurals = json.loads((ROOT / "data/raw/thirukkural.json").read_text(encoding="utf-8"))["kural"]
    by_num = {k["Number"]: k for k in kurals}

    lab = read("data/labels/silver_labels.csv")
    cand_nums = {int(r["number"]) for r in lab}
    for r in lab:
        n = int(r["number"])
        ex.append(example(f"Thirukkural {n}", ("kural", int(r["chapter"])), r["tamil"], r["label"],
                          r["science_concept"], hints_kural(by_num[n]), r["translation"], r["commentary_mk"]))
    rest = [k for k in kurals if k["Number"] not in cand_nums]
    for k in random.sample(rest, 100):
        ex.append(example(f"Thirukkural {k['Number']}", ("kural", (k["Number"] - 1) // 10 + 1),
                          f"{k['Line1']} / {k['Line2']}", "N", "", hints_kural(k), k["Translation"], k["mk"]))

    seen = set()
    pool = []

    def add_arutpa(r, label, concept):
        key = (r["section_id"], r["stanza_no"])
        if key in seen:
            return
        seen.add(key)
        pool.append((r, label, concept))
        ex.append(example(f"Thiruvarutpa {r['section_title']} stanza {r['stanza_no']}",
                          ("arutpa", r["section_id"]), r["text"], label, concept, hints_arutpa(r["text"])))

    for r in read("data/labels/arutpa_silver_labels.csv"):
        add_arutpa(r, r["label"], r["science_concept"])
    for r in read("data/labels/arutpa_silver_round2.csv"):
        add_arutpa(r, r["label"], r["notes"].split("; ", 1)[-1] if r["label"] == "A" else "")
    new_A = {5: "many named spaces (element-space, mind-space...) as levels of space",
             10: "supreme space arranged within pure space", 11: "space beyond space, hierarchy of spaces",
             24: "nine spaces contained within a central space"}
    for i, r in enumerate(read("data/processed/arutpa_new_candidates.csv")):
        add_arutpa(r, "A" if i in new_A else "M", new_A.get(i, ""))

    # extra negatives with no keyword hit at all (what a random stanza looks like)
    rows = [json.loads(l) for l in (ROOT / "data/processed/thiruvarutpa.jsonl").read_text(encoding="utf-8").splitlines()]
    rnd = [r for r in rows if (r["section_id"], r["stanza_no"]) not in seen]
    for r in random.sample(rnd, 120):
        ex.append(example(f"Thiruvarutpa {r['section_title']} stanza {r['stanza_no']}",
                          ("arutpa", r["section_id"]), r["text"], "N", "", hints_arutpa(r["text"])))

    def is_val(group):
        return int(hashlib.md5(str(group).encode()).hexdigest(), 16) % 5 == 0

    OUT.mkdir(parents=True, exist_ok=True)
    tr, va = [], []
    for g, e in ex:
        (va if is_val(g) else tr).append(e)
    tr_rep = []
    for e in tr:
        tr_rep += [e] * (REPEAT_POS if e["label"] in ("L", "O", "A") else 1)
    random.shuffle(tr_rep)
    for name, data in (("sft_train.jsonl", tr_rep), ("sft_val.jsonl", va)):
        with (OUT / name).open("w", encoding="utf-8") as f:
            for e in data:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
        c = {}
        for e in data:
            c[e["label"]] = c.get(e["label"], 0) + 1
        print(name, len(data), dict(sorted(c.items())))

    # sweep inputs: embedding finds the model has not seen
    todo = []
    for r in read("data/processed/arutpa_embedding_finds.csv"):
        if (r["section_id"], r["stanza_no"]) not in seen:
            src = f"Thiruvarutpa {r['section_title']} stanza {r['stanza_no']}"
            todo.append({"source": src, "url": r["source_url"], "messages": [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": user_prompt(src, r["text"], hints_arutpa(r["text"]))}]})
    with (OUT / "sweep_inputs.jsonl").open("w", encoding="utf-8") as f:
        for t in todo:
            f.write(json.dumps(t, ensure_ascii=False) + "\n")
    print("sweep_inputs.jsonl", len(todo))


if __name__ == "__main__":
    main()
