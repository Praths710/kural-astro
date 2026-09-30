"""Turn the raw Tolkappiyam and Thiruppavai sources into one JSON line per verse.

Tolkappiyam: the Central Institute of Classical Tamil (CICT) digital edition embeds every sutra (text + Tamil
explanation) as JSON in its portal page (github.com/cictdl/Tolkappiyam).
Thiruppavai: Andal's 30 pasurams from Tamil Wikisource (public domain); bracketed word glosses are removed.

Output: data/processed/tolkappiyam.jsonl (with explanations, local only), tolkappiyam_text.jsonl (deployed),
        data/processed/thiruppavai.jsonl
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW, OUT = ROOT / "data/raw", ROOT / "data/processed"
TOLKA_URL = "https://github.com/cictdl/Tolkappiyam"
PAVAI_URL = "https://ta.wikisource.org/wiki/திருப்பாவை"


def tolkappiyam():
    html = (RAW / "tolkappiyam/cict_portal.html").read_text(encoding="utf-8")
    data = json.loads(re.search(r'<script id="data" type="application/json">(.*?)</script>', html, re.S).group(1))
    rows, n = [], 0
    for adhikaram in data["tree"]:
        for iyal in adhikaram["i"]:
            for v in iyal["v"]:
                n += 1
                rows.append({"no": n, "adhikaram": adhikaram["n"], "iyal": iyal["n"], "iyal_no": v.get("mn"),
                             "title": re.sub(r"^\d+\.\s*", "", v.get("t", "")).strip(), "text": v["m"].strip(),
                             "explanation": v.get("u", "").strip(), "source_url": TOLKA_URL})
    assert data["meta"]["total"] == len(rows), (data["meta"]["total"], len(rows))
    return rows


def thiruppavai():
    w = (RAW / "thiruppavai/wikisource_thiruppavai.txt").read_text(encoding="utf-8")
    w = w.split("===ஆண்டாள் அருளிச்செய்த திருப்பாவை===", 1)[1].split("[[பகுப்பு", 1)[0]
    parts = re.split(r"(?m)^\s*(\d{1,2})\.\s*", w)
    rows = []
    for i in range(1, len(parts) - 1, 2):
        lines = [re.sub(r"\[[^\]]*\]", "", l).strip() for l in parts[i + 1].splitlines()]
        text = "\n".join(l for l in lines if l)
        rows.append({"no": int(parts[i]), "text": text, "source_url": PAVAI_URL})
    assert [r["no"] for r in rows] == list(range(1, 31)), [r["no"] for r in rows]
    return rows


if __name__ == "__main__":
    tolka = tolkappiyam()
    # the sutras are ancient (public domain); CICT's modern explanations stay local (labelling input only),
    # so the deployed app gets a text-only copy
    public = [{k: v for k, v in r.items() if k != "explanation"} for r in tolka]
    for name, rows in (("tolkappiyam", tolka), ("tolkappiyam_text", public), ("thiruppavai", thiruppavai())):
        (OUT / f"{name}.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
        print(name, len(rows))
