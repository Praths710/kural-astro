"""Fetch Thiruvarutpa (Vallalar) from thiruarutpa.org into data/raw/thiruvarutpa/ (cached HTML)
and parse to data/processed/thiruvarutpa.jsonl (one record per stanza).

Polite by design: single thread, 1s delay, every page cached so reruns cost nothing.
Source text (c) the publishers; used here for non-commercial academic research with attribution.
"""
import html
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "thiruvarutpa"
OUT = ROOT / "data" / "processed" / "thiruvarutpa.jsonl"
BASE = "https://www.thiruarutpa.org"
VOLUMES = ["First", "Second", "Third", "Fourth", "Fifth", "Sixth"]
UA = {"User-Agent": "Mozilla/5.0 (academic research; kural-astro project)"}
DELAY = 1.0


def get(url, cache_name):
    path = RAW / cache_name
    if path.exists() and path.stat().st_size > 2000:
        return path.read_text(encoding="utf-8")
    time.sleep(DELAY)
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=60) as r:
        data = r.read().decode("utf-8", errors="replace")
    path.write_text(data, encoding="utf-8")
    return data


def sections(vol_html):
    out, seen = [], set()
    for href in re.findall(r'href="(/thirumurai/v/(T\d+)/tm/([^"]+))"', vol_html):
        if href[1] not in seen:
            seen.add(href[1])
            out.append((href[1], href[2], href[0]))
    return out


def to_text(page):
    body = re.sub(r"<script.*?</script>|<style.*?</style>", "", page, flags=re.S)
    body = re.sub(r"<br\s*/?>|</p>|</div>|</tr>|</li>", "\n", body)
    body = html.unescape(re.sub(r"<.*?>", "", body))
    return [ln.strip() for ln in body.splitlines() if ln.strip()]


JUNK = re.compile(r"//|\.mp3|^Download$|^\[\d+(-\d+)?,\s*\d+\]|^\d+-\d{3}-\d{4}")


def parse_section(lines):
    start = next((i for i, l in enumerate(lines) if "திருச்சிற்றம்பலம்" in l), 0)
    title = next((l for l in lines if re.match(r"^\d{3}\.\s", l)), "")
    stanzas, cur = [], None
    for l in lines[start + 1:]:
        if re.search(r"(Thirumurai\s*Index|Copyright|Powered by)", l):
            break
        m = re.match(r"^(\d+)\.\s*(.*)", l)
        if m:
            if cur:
                stanzas.append(cur)
            cur = {"no": int(m.group(1)), "lines": [m.group(2)] if m.group(2) else [], "closed": False}
        elif cur:
            if JUNK.search(l):
                cur["closed"] = True
            elif not cur["closed"]:
                cur["lines"].append(l)
    if cur:
        stanzas.append(cur)
    return title, stanzas


def main():
    RAW.mkdir(parents=True, exist_ok=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    total_sec = total_st = 0
    with OUT.open("w", encoding="utf-8") as f:
        for vi, vol in enumerate(VOLUMES, 1):
            vhtml = get(f"{BASE}/Thirumurai/{vol}/tm", f"vol{vi}_index.html")
            secs = sections(vhtml)
            print(f"volume {vi} ({vol}): {len(secs)} sections", flush=True)
            for sid, slug, href in secs:
                try:
                    page = get(BASE + href, f"sec_{sid}.html")
                except Exception as e:
                    print(f"  FAIL {sid} {slug}: {e}", file=sys.stderr, flush=True)
                    continue
                title, stanzas = parse_section(to_text(page))
                total_sec += 1
                for st in stanzas:
                    total_st += 1
                    f.write(json.dumps({
                        "volume": vi, "section_id": sid, "section_slug": slug,
                        "section_title": title, "stanza_no": st["no"],
                        "text": "\n".join(st["lines"]),
                        "source_url": BASE + href,
                    }, ensure_ascii=False) + "\n")
    print(f"done: {total_sec} sections, {total_st} stanzas -> {OUT}")


if __name__ == "__main__":
    main()
