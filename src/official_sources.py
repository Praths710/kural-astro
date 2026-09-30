"""Research papers and images from verified sources only (no preprint servers).

Papers: Crossref (the DOI registry): any peer reviewed journal or conference paper with a registered DOI, e.g. IEEE, Elsevier,
Springer Nature, IOP, the AAS, Oxford (MNRAS) and APS, each linking to its official DOI page; plus NASA's
Technical Reports Server (NTRS). Images: the NASA Image and Video Library.
All calls go through curl (as the rest of the app does) and return [] on any failure.
"""
import html
import json
import re
import subprocess
import urllib.parse

UA = "KuralAstro/1.0 (student research project; mailto:praths710@gmail.com)"

# publisher name (as Crossref reports it, lower case) -> short label shown in the app
PUBLISHERS = [
    ("institute of electrical and electronics engineers", "IEEE"), ("ieee", "IEEE"),
    ("american astronomical society", "AAS"), ("iop publishing", "IOP"),
    ("oxford university press", "Oxford (MNRAS)"), ("american physical society", "APS"),
    ("springer", "Springer Nature"), ("nature", "Nature"), ("elsevier", "Elsevier"),
    ("edp sciences", "EDP (A&A)"), ("american association for the advancement of science", "Science (AAAS)"),
    ("american geophysical union", "AGU"), ("wiley", "Wiley"), ("cambridge university press", "Cambridge"),
    ("aip publishing", "AIP"), ("annual reviews", "Annual Reviews"), ("royal society", "Royal Society"),
    ("american meteorological society", "AMS"), ("optica", "Optica"), ("world scientific", "World Scientific"),
]


NON_SCIENCE = re.compile(r"philosoph|religio|theolog|buddh|hindu|spiritual|literature|linguistic|humanit|history of|"
                         r"finance|econom|stock|business|marketing|psycholog|educat|teach", re.I)


# publishers widely listed as predatory or low quality, plus humanities aggregators: never shown as dependable
NOT_DEPENDABLE = re.compile(
    r"scientific research publishing|international journal of science and research|naksh|uniscience|nan yang academy|"
    r"science publishing group|omics|longdom|hilaris|pulsus|walsh medical|juniper publishers|austin publishing|"
    r"lupine|crimson publishers|iris publishers|allied academies|gavin publishers|ecronicon|scitechnol|medwin|"
    r"iosr|global journals|research publish|scholars research library|ijraset|ijrar|academic journals inc|"
    r"project muse|jstor|chartered institute of brewers", re.I)


def _get(url, timeout=25):
    try:
        r = subprocess.run(["curl", "-s", "-L", "-m", str(timeout), "-A", UA, url], capture_output=True, timeout=timeout + 5)
        return json.loads(r.stdout.decode("utf-8"))
    except (subprocess.SubprocessError, OSError, ValueError, UnicodeDecodeError):
        return None


def _clean(t):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", t or ""))).strip()


def plain_query(q):
    """'all:"extra dimensions" AND all:braneworld' -> 'extra dimensions braneworld'."""
    return re.sub(r"\s+", " ", re.sub(r'all:|"|\bAND\b|\bOR\b|[()]', " ", q)).strip()


def publisher_label(name):
    n = (name or "").lower()
    return next((label for key, label in PUBLISHERS if key in n), None)


def crossref(query, rows=40):
    """Peer-reviewed articles from notable publishers, most relevant first."""
    params = urllib.parse.urlencode({
        "query": query, "rows": rows, "filter": "type:journal-article,type:proceedings-article",
        "select": "DOI,title,publisher,issued,container-title,author,is-referenced-by-count",
        "mailto": "praths710@gmail.com"})
    d = _get("https://api.crossref.org/works?" + params)
    out = []
    for w in ((d or {}).get("message") or {}).get("items", []):
        # any peer reviewed journal or conference paper with a registered DOI counts as a verified source;
        # well-known publishers get a short label, others keep their registered publisher name
        label = publisher_label(w.get("publisher")) or _clean(w.get("publisher", ""))[:40]
        title = _clean((w.get("title") or [""])[0])
        year = ((w.get("issued") or {}).get("date-parts") or [[None]])[0][0]
        venue = _clean((w.get("container-title") or [""])[0])
        if not (label and venue and title and year and w.get("DOI")) or NON_SCIENCE.search(venue) \
                or NOT_DEPENDABLE.search(f'{w.get("publisher", "")} {venue}'):
            continue
        out.append({"title": title, "url": "https://doi.org/" + w["DOI"], "year": str(year),
                    "authors": [" ".join(x for x in (a.get("given"), a.get("family")) if x) for a in (w.get("author") or [])[:4]],
                    "venue": _clean((w.get("container-title") or [""])[0]), "publisher": label,
                    "citations": w.get("is-referenced-by-count") or 0})
    return out


def ntrs(query, size=8):
    """NASA Technical Reports Server."""
    d = _get("https://ntrs.nasa.gov/api/citations/search?" + urllib.parse.urlencode({"q": query, "page.size": size}))
    out = []
    for r in (d or {}).get("results", []):
        pubs = r.get("publications") or [{}]
        year = (pubs[0].get("publicationDate") or r.get("submittedDate") or "")[:4]
        authors = [((a.get("meta") or {}).get("author") or {}).get("name", "") for a in (r.get("authorAffiliations") or [])[:4]]
        if r.get("id") and r.get("title") and year.isdigit():
            out.append({"title": _clean(r["title"]), "url": f"https://ntrs.nasa.gov/citations/{r['id']}", "year": year,
                        "authors": [a for a in authors if a], "venue": "NASA Technical Reports Server", "publisher": "NASA",
                        "citations": 0})
    return out


STOP = {"the", "and", "with", "from", "into", "within", "that", "this", "their", "which", "over", "under", "about",
        "between", "through", "during", "theory", "study", "analysis", "concept", "concepts", "model", "models"}


def _stems(text):
    """Crude stems: drop a plural 's' ('holes' -> 'hole'), then keep the first 6 letters."""
    words = (w for w in re.findall(r"[a-z]{4,}", text.lower()) if w not in STOP)
    return {(w[:-1] if len(w) > 4 and w.endswith("s") and not w.endswith("ss") else w)[:6] for w in words}


def relevant(title, query, need=0.6):
    """Keep a paper only if its title carries most of the query's key words (crude but transparent)."""
    q = _stems(query)
    want = len(q) if len(q) <= 2 else max(2, round(need * len(q)))   # short queries: every key word
    return not q or len(q & _stems(title)) >= want


def papers(query):
    """Up to ~10 papers: the most cited and the most recent notable-publisher articles, plus NASA reports."""
    found = [p for p in crossref(query) if relevant(p["title"], query)]
    cited = sorted(found, key=lambda p: -p["citations"])[:4]
    recent = sorted((p for p in found if p not in cited), key=lambda p: -int(p["year"]))[:4]
    out = [{**p, "tag": "foundational"} for p in cited] + [{**p, "tag": "recent"} for p in recent]
    out += [{**p, "tag": "nasa"} for p in ntrs(query, 8) if relevant(p["title"], query)][:3]
    seen, uniq = set(), []
    for p in out:
        if p["url"] not in seen:
            seen.add(p["url"])
            uniq.append(p)
    return uniq


def nasa_images_best(query, limit=6):
    """Long concept phrases rarely match image titles: fall back to each comma part, then the first words."""
    tries = [query] + [c.strip() for c in re.split(r",|;|\band\b", query) if len(c.strip()) > 3] + [" ".join(query.split()[:2])]
    out, seen = [], set()
    for q in dict.fromkeys(tries):
        for img in nasa_images(q, limit):
            if img["url"] not in seen:
                seen.add(img["url"])
                out.append(img)
        if len(out) >= limit:
            break
    return out[:limit]


def nasa_images(query, limit=6):
    """Official images from the NASA Image and Video Library (public domain unless noted)."""
    d = _get("https://images-api.nasa.gov/search?" + urllib.parse.urlencode({"q": query, "media_type": "image"}))
    out = []
    for it in (((d or {}).get("collection") or {}).get("items") or [])[:limit * 2]:
        meta, links = (it.get("data") or [{}])[0], it.get("links") or []
        thumb = next((l["href"] for l in links if l.get("href", "").startswith("https://")), "")
        if not (meta.get("nasa_id") and thumb):
            continue
        out.append({"title": _clean(meta.get("title", ""))[:140], "center": meta.get("center") or "NASA",
                    "year": (meta.get("date_created") or "")[:4], "thumb": thumb.replace(" ", "%20"),
                    "url": "https://images.nasa.gov/details/" + urllib.parse.quote(meta["nasa_id"]),
                    "description": _clean(meta.get("description", ""))[:260]})
        if len(out) >= limit:
            break
    return out
