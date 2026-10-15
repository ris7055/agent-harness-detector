FROM python:3.11-slim

WORKDIR /app

# Shared core package (build context = repo root)
COPY core/ ./core/
RUN pip install --no-cache-dir ./core

COPY services/portal/requirements.txt ./services/portal/requirements.txt
RUN pip install --no-cache-dir -r services/portal/requirements.txt

COPY services/portal/ ./services/portal/

WORKDIR /app/services/portal
EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
