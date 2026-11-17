FROM python:3.13-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
 && python -m playwright install --with-deps --only-shell chromium
COPY app ./app

ENV PRICEWATCHER_DB=/data/pricewatcher.db
VOLUME /data
EXPOSE 8000

# Exactly 1 worker: the scheduler runs in-process, more workers would check everything twice.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
