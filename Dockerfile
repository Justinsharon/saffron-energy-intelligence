# Saffron Suites forecast / plan API (api/main.py) for Cloud Run. Build context: the repo root (needs src/ and models/).
#   gcloud run deploy saffron-api --source . --region asia-south1 ...   (see CLAUDE.md, "API")
# Python matches the environment that fitted the models (3.14, uv.lock), so the saved scikit-learn / LightGBM models load unchanged.
FROM python:3.14-slim
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY api/requirements.txt api/requirements.txt
RUN pip install --no-cache-dir -r api/requirements.txt
COPY src/ src/
COPY models/ models/
COPY api/ api/
ENV PYTHONPATH=/app/src PYTHONUNBUFFERED=1 PORT=8080
CMD exec uvicorn api.main:app --host 0.0.0.0 --port ${PORT} --workers 1
