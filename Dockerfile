FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8787 \
    TZ=Europe/Berlin

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl tzdata \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user and /data directory
RUN useradd -m -u 1000 appuser \
    && mkdir -p /data \
    && chown -R appuser:appuser /data

WORKDIR /app

COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

COPY app /app/app

USER appuser

EXPOSE 8787

HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD curl -fsS http://127.0.0.1:8787/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8787"]

