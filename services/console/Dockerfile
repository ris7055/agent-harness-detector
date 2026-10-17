FROM python:3.11-slim

WORKDIR /app

# Shared core package (build context = repo root)
COPY core/ ./core/
RUN pip install --no-cache-dir ./core

COPY services/console/requirements.txt ./services/console/requirements.txt
RUN pip install --no-cache-dir -r services/console/requirements.txt

COPY services/console/ ./services/console/

WORKDIR /app/services/console
EXPOSE 8082
CMD exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8082}
