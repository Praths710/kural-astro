# kural-astro

Mining Tamil classical texts (Thirukkural first; Thiruppavai, Thiruvarutpa later) for
verses that encode natural/astronomical content, then linking them to modern science
with retrieval-grounded LLM interpretation.

## Pipeline

1. `src/candidates.py`  keyword retrieval -> `data/processed/candidates.csv` (330 of 1330 kurals)
2. `src/silver_labels.py` provisional labels -> `data/labels/silver_labels.csv`
   (L literal / O observation-in-simile / A ambiguous / M metaphor / N spurious)
3. Human verification of labels (required before any training)
4. Track A: classifier (IndicBERT/MuRIL) on verified labels -> needs GPU (Colab/Kaggle)
5. Track B: RAG over arXiv/NASA ADS + prompted LLM, shuffle-control evaluation

## Findings so far (silver, unverified)

Of 1330 kurals: 11 L, 13 O, 8 A. Only ~4 touch astronomy proper (782, 957, 1117 lunar
phases/spots; 371 star-influence belief); 610 is mythic cosmology. The strongest block is
the rain chapter (kurals 11-20), i.e. hydrology/monsoon, not astrophysics.

## Thiruvarutpa (Vallalar)

`src/fetch_thiruvarutpa.py` scrapes thiruarutpa.org (385 sections, 8,109 stanzas, Tamil only) ->
`data/processed/thiruvarutpa.jsonl`. `src/candidates_arutpa.py` -> 258 candidates.
`src/silver_labels_arutpa.py` (silver, unverified): 63 A (mystic-cosmological), 3 O, 150 M, 42 N.
The A set holds the real material: nested/multiple universes, universes inside an atom, layered
spaces, one light pervading all universes. Keyword recall is unmeasured; embedding search is next.

## Data

Thirukkural JSON: https://github.com/tk120404/thirukkural (Apache-2.0).

## Embedding search (round 2)

`src/embed_search.py` (multilingual-e5-small, CPU, run in `.venv`): leave-one-out recall@500 = 32%
(random 6%), median rank 1827/8109, so retrieval is weak on classical Tamil. Top-60 review:
6 real new cosmological stanzas (10%), rest generic light/grace devotion. All 6 use வெளி compounds
(பரவெளி, நடுவெளி, ஏழ்வெளி...) that the keyword lexicon missed because bare வெளி is noisy.
Round-2 labels: `data/labels/arutpa_silver_round2.csv` (top 60 only; ranks 61-200 unreviewed).

## LLM fine-tune

`src/build_sft.py` -> `data/train/sft_{train,val}.jsonl` (648 / 172 examples; split by chapter/section;
train has 11 L, 14 O, 59 A; val has 22 A, 2 O, no L, so L/O generalisation is untestable).
`notebooks/train_lora.ipynb` (Colab GPU, Unsloth QLoRA, Qwen2.5-3B default) trains and evaluates it.
Labels are silver/unverified: metrics are provisional. Real-world research links need a retrieval layer.

## Research-link report and sweep

`src/research_report.py` maps verse concepts to analogy topics and pulls real papers from arXiv
(via curl; Python's client gets 406) -> `reports/verse_science_report.md`.
`data/train/sweep_inputs.jsonl` (140 unseen embedding finds) + a notebook cell run the trained model
over them and download `predictions.jsonl`. Next: feed predictions back into the report script.

## Web app

`python src/app.py` -> http://localhost:8765 (stdlib only; needs `.env` with GEMINI_API_KEY).
Sections: hero search, cosmic map (topic planets sized by verse count), explore (topic -> verses +
live arXiv), bring-your-own-verse, archive. Every verse opens a deep-reading modal: literal meaning,
the analogy + strength, AI-summarised real-world examples, live arXiv papers. Concepts, planets and
chips all route back into search. Frontend: `src/webapp/index.html` (single file, no build).

## Login

Every page and API route needs a signed-in account (`src/auth.py`): PBKDF2-SHA256 salted hashes in
`data/users.json`, HMAC-signed HttpOnly session cookie (Secure behind HTTPS), 10-failure lockout per IP.
Set `INVITE_CODE` to require a code at sign-up (recommended once public: every user spends your Gemini quota).

## Deploy

Environment variables: `GEMINI_API_KEY` (required), `SECRET_KEY` (keeps sessions valid across restarts),
`INVITE_CODE` (optional), `PORT` (set by the host). The `Dockerfile` ships only the app + the four data
files it reads; `.env` is never included.

- **Render**: push this folder to GitHub -> render.com -> New -> Blueprint -> pick the repo (`render.yaml`)
  -> enter `GEMINI_API_KEY` / `INVITE_CODE` -> URL like `https://kural-astro.onrender.com`.
  Free tier sleeps after ~15 min idle (first visit then takes ~1 min) and its disk resets on
  restart/redeploy, so accounts must be re-created after a redeploy.
- **Hugging Face Spaces**: new Space, SDK = Docker, push this folder; add the same variables as Space
  secrets. Port 7860 already matches.
