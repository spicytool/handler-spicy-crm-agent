FROM python:3.12-slim

WORKDIR /app

RUN useradd -m -u 1000 appuser

COPY --chown=appuser:appuser requirements.txt .

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

COPY --chown=appuser:appuser handler/ ./handler/

USER appuser

EXPOSE 8080

CMD ["uvicorn", "handler.webhooks:app", "--host", "0.0.0.0", "--port", "8080"]
