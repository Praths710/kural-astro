"""English translations for the astronomy verses (Thirukkural already has its standard English).

Writes data/labels/astro_english.json: id -> faithful English translation. Run again to resume.
Verses outside this set are translated on demand by the app (/api/translate) and cached.
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gemini_label as gl   # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "labels" / "astro_english.json"
BATCH = 25
SYSTEM = (
    "Translate each classical Tamil verse into clear, faithful modern English for students. Keep the poet's images "
    "(sun, moon, sky, light, worlds) exactly as they are; do not add explanations, modern science or commentary. "
    "Keep it to the verse's own length. Tolkappiyam ids (tolka:) are grammar sutras: translate the sutra itself.\n"
    "Return ONLY a JSON array of {id, english}, one per input verse, same order, same ids."
)


def main():
    import app
    done = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    texts = {v["id"]: v for v in gl.load_verses()}
    todo = [v for v in app.verse_list() if v["astro"] and not v.get("english") and v["id"] not in done]
    print(f"{len(done)} done, {len(todo)} to go", flush=True)
    gl.SYSTEM = SYSTEM
    for i in range(0, len(todo), BATCH):
        batch = [{"id": v["id"], "text": v["tamil"].replace("\n", " ")} for v in todo[i:i + BATCH]]
        result = gl.call_gemini(batch)
        if result is None:
            print("no answer after retries, stopping (run again to resume)", flush=True)
            break
        for r in result:
            if isinstance(r, dict) and r.get("id") in texts and str(r.get("english") or "").strip():
                done[r["id"]] = str(r["english"]).strip()[:1500]
        OUT.write_text(json.dumps(done, ensure_ascii=False, indent=0), encoding="utf-8")
        print(f"{min(i + BATCH, len(todo))}/{len(todo)}", flush=True)
        time.sleep(4)
    print("saved", len(done), "->", OUT)


if __name__ == "__main__":
    main()
