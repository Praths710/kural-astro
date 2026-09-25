FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -m -u 1000 app

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY src/app.py src/auth.py src/library.py src/store.py src/gemini_label.py src/research_report.py src/
COPY src/webapp/ src/webapp/
COPY data/raw/thirukkural.json data/raw/
COPY data/processed/thiruvarutpa.jsonl data/processed/arxiv_cache.json data/processed/
COPY data/labels/gemini_labels_dedup.json data/labels/
RUN chown -R app:app /app/data

USER app
ENV HOST=0.0.0.0 PORT=7860 PYTHONUNBUFFERED=1 PYTHONIOENCODING=utf-8
EXPOSE 7860
HEALTHCHECK --interval=30s --timeout=5s CMD curl -fs http://localhost:${PORT}/health || exit 1
CMD ["python", "src/app.py"]
