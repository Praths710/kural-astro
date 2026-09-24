"""Fast, parallel labeling of a priority verse list (used under a hard time budget).
Same output schema/file as gemini_label.py so results merge into one dataset."""
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gemini_label as g

BATCH = 20
WORKERS = 4


def main():
    ids = set(json.loads((g.ROOT / "data/processed/priority_ids.json").read_text()))
    all_v = {v["id"]: v for v in g.load_verses()}
    verses = [all_v[i] for i in ids if i in all_v]
    print(f"{len(verses)} priority verses to label with {WORKERS} workers")

    batches = [verses[i:i + BATCH] for i in range(0, len(verses), BATCH)]
    t0 = time.time()
    done = 0
    with g.OUT.open("a", encoding="utf-8") as f, ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {ex.submit(g.call_gemini, b): b for b in batches}
        for fut in as_completed(futs):
            b = futs[fut]
            try:
                result = fut.result()
            except Exception as e:
                print("batch error:", e, file=sys.stderr)
                result = None
            if result is None:
                print(f"batch of {len(b)} FAILED, skipping", file=sys.stderr)
                continue
            by_id = {r.get("id"): r for r in result if isinstance(r, dict)}
            for v in b:
                r = by_id.get(v["id"], {"id": v["id"], "label": "PARSE_ERROR", "science_concept": "", "meaning": ""})
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
            f.flush()
            done += len(b)
            print(f"{done}/{len(verses)}  elapsed={time.time()-t0:.0f}s")
    print("done in", round(time.time() - t0), "s")


if __name__ == "__main__":
    main()
