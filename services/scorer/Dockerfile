FROM python:3.11-slim

# libgomp1 is required by xgboost (not in the slim image)
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Shared core package (build context = repo root)
COPY core/ ./core/
RUN pip install --no-cache-dir ./core

COPY services/scorer/requirements.txt ./services/scorer/requirements.txt
RUN pip install --no-cache-dir -r services/scorer/requirements.txt

COPY services/scorer/ ./services/scorer/

WORKDIR /app/services/scorer
EXPOSE 8081
CMD exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8081}
