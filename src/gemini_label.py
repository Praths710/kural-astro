"""Label the FULL corpus (all Thirukkural + Thiruvarutpa verses, not just keyword candidates)
with the free Gemini API. Batches verses per request to fit the free-tier rate limit, and
writes each batch to disk immediately so an interruption loses at most one batch.

Labels: L literal natural fact / O observation-in-simile / A mystic-cosmological (analogy only)
        / M metaphor or devotion / N no physical content.
Output: data/labels/gemini_labels.jsonl (one line per verse). Run again to resume: already-done
verses are skipped.
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_key():
    if os.environ.get("GEMINI_API_KEY"):
        return os.environ["GEMINI_API_KEY"].strip()
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.startswith("GEMINI_API_KEY="):
                return line.split("=", 1)[1].strip()
    return ""


KEY = _load_key()
URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash-lite:generateContent"
KEY_HEADER = f"x-goog-api-key: {KEY}"
OUT = ROOT / "data" / "labels" / "gemini_labels.jsonl"
BATCH = 12
RPM_DELAY = 8.0  # unknown free-tier limit for this model; conservative until proven otherwise

SYSTEM = (
    "You are labelling classical Tamil verses for natural-science content, for an academic "
    "project. For EACH verse return one JSON object with: id, label (one of L/O/A/M/N), "
    "science_concept (short phrase, empty string if label is M or N), meaning (<=15 words).\n"
    "L = states a natural/physical fact literally (e.g. rain -> crops, moon phases).\n"
    "O = a real natural observation embedded in a simile/comparison.\n"
    "A = a mystic-cosmological claim with real scale/structure content (nested or countless "
    "universes, universe(s) inside an atom, layered/many 'spaces', light pervading the cosmos). "
    "Only use A if there is genuine spatial/cosmic scale content, not generic praise of god as light.\n"
    "M = natural or cosmic-sounding words used as ordinary metaphor/devotional praise, no real "
    "physical or cosmic-scale content.\n"
    "N = the verse has no natural-science content at all (ethics, love, court life, etc).\n"
    "Ancient poets did not know modern physics: A/O/L are about content in the verse, never a "
    "claim the poet anticipated science. Return ONLY a JSON array, one object per input verse, "
    "same order, same ids. No other text.\n\n"
    "Calibration examples (apply the same standard even to a single verse with no other context):\n"
    '{"id":"ex1","text":"அண்டங்கள் எல்லாம் அணுவில் அடைத்தருளி"} -> '
    '{"id":"ex1","label":"A","science_concept":"universes contained within an atom",'
    '"meaning":"All universes are held within an atom."}\n'
    '{"id":"ex2","text":"வான்நின்று உலகம் வழங்கி வருதலால்"} -> '
    '{"id":"ex2","label":"L","science_concept":"rain sustains life on earth",'
    '"meaning":"The world survives because rain never fails."}\n'
    '{"id":"ex3","text":"திங்கள் அணிந்தருள் சிவனேயோ"} -> '
    '{"id":"ex3","label":"M","science_concept":"",'
    '"meaning":"Devotional address to Shiva wearing the moon; ordinary iconography, no scale/structure content."}\n'
    '{"id":"ex4","text":"அகர முதல எழுத்தெல்லாம் ஆதி பகவன் முதற்றே உலகு"} -> '
    '{"id":"ex4","label":"N","science_concept":"","meaning":"God as the origin of all things; no natural-science content."}'
)


def call_gemini(verses):
    user = "\n".join(f'{{"id":"{v["id"]}","text":"{v["text"][:500]}"}}' for v in verses)
    body = json.dumps({
        "contents": [{"parts": [{"text": SYSTEM + "\n\nVerses:\n" + user}]}],
        "generationConfig": {"temperature": 0, "responseMimeType": "application/json"},
    })
    for attempt in range(10):
        r = subprocess.run(["curl", "-s", "-m", "90", "-H", "Content-Type: application/json", "-H", KEY_HEADER,
                            "-d", body, URL], capture_output=True, text=True)
        try:
            resp = json.loads(r.stdout)
        except json.JSONDecodeError:
            time.sleep(min(15 * (attempt + 1), 90))
            continue
        if "error" in resp:
            msg = resp["error"].get("message", "")
            if resp["error"].get("code") == 429 or "quota" in msg.lower():
                print("  rate-limited, waiting 60s...", file=sys.stderr)
                time.sleep(60)
                continue
            if "high demand" in msg.lower() or resp["error"].get("code") in (500, 503):
                wait = min(20 * (attempt + 1), 120)
                print(f"  server busy (attempt {attempt+1}/10), waiting {wait}s...", file=sys.stderr)
                time.sleep(wait)
                continue
            raise RuntimeError(msg)
        text = resp["candidates"][0]["content"]["parts"][0]["text"]
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            time.sleep(5)
            continue
    return None


def load_verses():
    out = []
    kurals = json.loads((ROOT / "data/raw/thirukkural.json").read_text(encoding="utf-8"))["kural"]
    for k in kurals:
        out.append({"id": f"kural:{k['Number']}", "text": f"{k['Line1']} {k['Line2']} | {k['Translation']}"})
    rows = [json.loads(l) for l in (ROOT / "data/processed/thiruvarutpa.jsonl").read_text(encoding="utf-8").splitlines()]
    for r in rows:
        out.append({"id": f"arutpa:{r['section_id']}:{r['stanza_no']}", "text": r["text"].replace("\n", " ")})
    return out


def main():
    verses = load_verses()
    done = set()
    if OUT.exists():
        for l in OUT.read_text(encoding="utf-8").splitlines():
            try:
                done.add(json.loads(l)["id"])
            except Exception:
                pass
    todo = [v for v in verses if v["id"] not in done]
    print(f"{len(verses)} total, {len(done)} already labelled, {len(todo)} remaining")
    with OUT.open("a", encoding="utf-8") as f:
        for i in range(0, len(todo), BATCH):
            batch = todo[i:i + BATCH]
            result = call_gemini(batch)
            if result is None:
                print(f"batch {i}: FAILED after retries, skipping (rerun later to retry it)", file=sys.stderr)
                time.sleep(RPM_DELAY)
                continue
            by_id = {r.get("id"): r for r in result if isinstance(r, dict)}
            for v in batch:
                r = by_id.get(v["id"])
                if r is None:
                    r = {"id": v["id"], "label": "PARSE_ERROR", "science_concept": "", "meaning": ""}
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
            f.flush()
            print(f"{i + len(batch)}/{len(todo)}", end="\r", flush=True)
            time.sleep(RPM_DELAY)
    print("\ndone ->", OUT)


if __name__ == "__main__":
    main()
