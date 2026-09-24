"""Embedding search over Thiruvarutpa: find stanzas semantically close to the labelled
cosmological (A/O) stanzas that the keyword pass missed.

Model: intfloat/multilingual-e5-small (covers Tamil). Run with the project venv (.venv).
Outputs data/processed/arutpa_embedding_finds.csv and prints a leave-one-out recall check.
Caveat: seeds came from keyword hits, so the check measures 'find more like these', not
'find cosmology worded differently'; reviewer judgement on the finds is the real test.
"""
import csv
import json
from pathlib import Path

import numpy as np
from sentence_transformers import SentenceTransformer

ROOT = Path(__file__).resolve().parent.parent
STANZAS = ROOT / "data" / "processed" / "thiruvarutpa.jsonl"
LABELS = ROOT / "data" / "labels" / "arutpa_silver_labels.csv"
EMB = ROOT / "data" / "processed" / "arutpa_emb.npy"
OUT = ROOT / "data" / "processed" / "arutpa_embedding_finds.csv"
MODEL = "intfloat/multilingual-e5-small"


def main():
    rows = [json.loads(l) for l in STANZAS.read_text(encoding="utf-8").splitlines()]
    key = {(r["section_id"], r["stanza_no"]): i for i, r in enumerate(rows)}
    if EMB.exists():
        E = np.load(EMB)
    else:
        model = SentenceTransformer(MODEL)
        model.max_seq_length = 256
        E = model.encode(["passage: " + r["text"].replace("\n", " ") for r in rows],
                         batch_size=32, normalize_embeddings=True, show_progress_bar=True)
        np.save(EMB, E)

    labs = list(csv.DictReader(LABELS.open(encoding="utf-8-sig")))
    pos_idx = [key[(l["section_id"], int(l["stanza_no"]))] for l in labs if l["label"] in ("A", "O")]
    cand_idx = {key[(l["section_id"], int(l["stanza_no"]))] for l in labs}
    P = E[pos_idx]

    # leave-one-out: rank of each held-out positive among all stanzas
    ranks = []
    for j, i in enumerate(pos_idx):
        cen = np.delete(P, j, axis=0).mean(axis=0)
        cen /= np.linalg.norm(cen)
        sims = E @ cen
        sims[[k for k in pos_idx if k != i]] = -1
        ranks.append(int((sims > sims[i]).sum()) + 1)
    ranks = np.array(ranks)
    n = len(rows)
    print(f"leave-one-out over {len(ranks)} positives among {n} stanzas:")
    print(f"  median rank {int(np.median(ranks))}  recall@100 {np.mean(ranks<=100):.0%}  "
          f"recall@500 {np.mean(ranks<=500):.0%}  (random recall@500 would be {500/n:.0%})")

    cen = P.mean(axis=0)
    cen /= np.linalg.norm(cen)
    sims = E @ cen
    nearest = (E @ P.T).argmax(axis=1)
    order = [i for i in np.argsort(-sims) if i not in cand_idx][:200]
    with OUT.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["rank", "sim", "volume", "section_id", "section_title", "stanza_no",
                    "text", "source_url", "label", "notes"])
        for r_, i in enumerate(order, 1):
            r = rows[i]
            w.writerow([r_, f"{sims[i]:.3f}", r["volume"], r["section_id"], r["section_title"],
                        r["stanza_no"], r["text"].replace("\n", " / "), r["source_url"], "", ""])
    print("wrote", OUT)


if __name__ == "__main__":
    main()
