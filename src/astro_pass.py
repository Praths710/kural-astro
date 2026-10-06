"""Second, astronomy-only labelling pass.

The first pass (gemini_label.py) asked a broad question ("any natural science?") and filed many sky verses as
metaphor or no science. This pass re-reads only the verses that mention the sky in Tamil (sun, moon, stars,
planets, sky, cosmos, eclipse) and asks one narrow question: does the verse describe something astronomical?

Output: data/labels/astro_labels.jsonl, one line per verse:
  {"id", "astro": true/false, "label": L/O/A, "theme": one of research_report.ASTRO_THEMES, "concept", "meaning"}
The first-pass labels are not changed. Run again to resume; stops cleanly when the daily quota runs out.
"""
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gemini_label as gl          # noqa: E402  (Gemini call, key, verse texts)
import research_report as rr       # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "labels" / "astro_labels.jsonl"
BATCH = 25
SKY = re.compile(r"ஞாயிறு|ஞாயிற்|பரிதி|இரவி|ரவி|சூரிய|கதிரவ|கதிர்|பகலவ|அருக்க|சுடர்|திங்கள|மதிய|நிலா|நிலவ|சந்திர|"
                 r"அம்புலி|பிறை|விண்மீன்|நாண்மீன்|நாள்மீன்|மீன்|தாரகை|நட்சத்திர|கோள்|வியாழ|செவ்வாய்|வெள்ளி|விசும்ப|"
                 r"ஆகாய|ககன|வான்|வானம|விண்|அண்ட|பிரபஞ்ச|புவன|கிரகண|இராகு|கேது|sun|moon|star|planet|sky|eclipse", re.I)

THEMES = "\n".join(f"  {k}: {rr.TOPICS[k][0]}" for k in rr.ASTRO_THEMES)
SYSTEM = (
    "You are checking classical Tamil verses for ASTRONOMY and ASTROPHYSICS content only, for an academic project.\n"
    "For EACH verse return one JSON object: id, astro (true/false), label (L/O/A), theme, concept, meaning.\n"
    "astro = true only if the verse says something about a celestial body or the cosmos as a physical thing: the Sun "
    "or Moon and their motion, phases, light or heat; stars, planets, eclipses; dawn or dusk as the Sun rising or "
    "setting; the sky as space; the size, number, nesting or structure of worlds and universes; light filling the "
    "cosmos. A simile counts when it states a real property (the waxing moon, the Sun dispelling darkness, a star "
    "fading at dawn).\n"
    "astro = false when a sky word is only a name, an epithet or ornament (Shiva wearing the crescent, 'my sun-like "
    "lord', 'heaven' as the afterlife), or when the verse is about rain, plants, animals, the body or ethics.\n"
    "label: L = states an astronomical fact plainly, O = a real sky observation inside a comparison, "
    "A = cosmic scale or structure (countless or nested universes, light pervading the cosmos).\n"
    "theme: the closest key from this list:\n" + THEMES + "\n"
    "concept: a short English phrase naming the astronomy idea (empty if astro is false). "
    "meaning: what the verse says, at most 15 words.\n"
    "Tolkappiyam ids (tolka:) come with a modern explanation after '|'; Thirukkural ids (kural:) with an English "
    "translation after '|'. Ancient poets did not know modern physics: judge only what the verse describes.\n"
    "Return ONLY a JSON array, one object per input verse, same order, same ids."
)


def candidates(done):
    import app   # verse_list carries the first-pass astro flag
    first = {v["id"]: v for v in app.verse_list()}
    return [v for v in gl.load_verses()
            if v["id"] in first and not first[v["id"]]["astro"] and v["id"] not in done and SKY.search(v["text"])]


ACCEPTED = ROOT / "data" / "labels" / "astro_accepted.json"
# the model still let through some ornaments and devotion ("Shiva wearing the crescent"): drop those by wording
NOT_SKY = re.compile(r"ornament|adorn|lock|hair|wear|crown|head|lamp|rain|heavenly|celestial state|nectar|honey|terrace|"
                     r"pavilion|conch|face|eyes|friendship|fragrance|praise|devot|worship|grace|lord|deity|god", re.I)
# read by hand and rejected: no real sky content (fate, an ascetic's day, a mansion "in the sky", yoga channels, botany)
REJECTED = {"kural:299", "kural:371", "arutpa:T157:35", "arutpa:T249:10", "arutpa:T250:21", "arutpa:T347:4",
            "arutpa:T349:21", "arutpa:T129:7", "arutpa:T207:180", "arutpa:T350:5", "arutpa:T160:141", "arutpa:T104:4",
            "arutpa:T267:8", "arutpa:T375:9", "arutpa:T233:9", "arutpa:T177:9", "arutpa:T158:370", "pavai:14",
            "tolka:1452"}


def build():
    """Write the reviewed result the site reads: id -> {label, theme, concept, meaning}."""
    rows = [json.loads(l) for l in OUT.read_text(encoding="utf-8").splitlines() if l.strip()]
    ok = {r["id"]: {k: r[k] for k in ("label", "theme", "concept", "meaning")} for r in rows
          if r["astro"] and r["id"] not in REJECTED and not NOT_SKY.search(f'{r["concept"]} {r["meaning"]}')}
    ACCEPTED.write_text(json.dumps(ok, ensure_ascii=False, indent=0), encoding="utf-8")
    print(f"{len(rows)} checked, {sum(r['astro'] for r in rows)} said yes, {len(ok)} accepted -> {ACCEPTED}")


def main():
    done = set()
    if OUT.exists():
        done = {json.loads(l)["id"] for l in OUT.read_text(encoding="utf-8").splitlines() if l.strip()}
    todo = candidates(done)
    print(f"{len(done)} already checked, {len(todo)} to go", flush=True)
    gl.SYSTEM = SYSTEM
    with OUT.open("a", encoding="utf-8") as f:
        for i in range(0, len(todo), BATCH):
            batch = todo[i:i + BATCH]
            result = gl.call_gemini(batch)
            if result is None:
                print(f"batch {i}: no answer after retries, stopping (run again later to resume)", flush=True)
                return
            by_id = {r.get("id"): r for r in result if isinstance(r, dict)}
            for v in batch:
                r = by_id.get(v["id"])
                if r is None:
                    continue            # left for the next run
                astro = r.get("astro") is True and r.get("theme") in rr.ASTRO_THEMES and r.get("label") in ("L", "O", "A")
                f.write(json.dumps({"id": v["id"], "astro": astro, "label": r.get("label", ""), "theme": r.get("theme", ""),
                                    "concept": str(r.get("concept") or "")[:120], "meaning": str(r.get("meaning") or "")[:200]},
                                   ensure_ascii=False) + "\n")
            f.flush()
            print(f"{min(i + BATCH, len(todo))}/{len(todo)}", flush=True)
            time.sleep(4)
    print("done ->", OUT)


if __name__ == "__main__":
    build() if sys.argv[1:] == ["build"] else main()
