FROM python:3.13-slim

WORKDIR /app
COPY requirements.txt .
# Playwright's bundled Node needs libatomic1 before it can install Chromium's own dependencies.
RUN apt-get update && apt-get install -y --no-install-recommends libatomic1 && rm -rf /var/lib/apt/lists/* \
 && pip install --no-cache-dir -r requirements.txt \
 && python -m playwright install --with-deps --only-shell chromium
COPY app ./app

ENV PRICEWATCHER_DB=/data/pricewatcher.db
VOLUME /data
EXPOSE 8000

# Exactly 1 worker: the scheduler runs in-process, more workers would check everything twice.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
