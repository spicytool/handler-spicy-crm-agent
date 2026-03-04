FROM python:3.12-slim

WORKDIR /app

RUN useradd -m -u 1000 appuser

COPY --chown=appuser:appuser requirements.txt .

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

COPY --chown=appuser:appuser handler/ ./handler/

USER appuser

EXPOSE 8080

WORKDIR /app/handler
CMD uvicorn webhooks:app --host 0.0.0.0 --port ${PORT:-8080}
