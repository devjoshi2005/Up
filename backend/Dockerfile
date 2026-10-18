FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# System deps for psycopg2 and healthchecks
RUN apt-get update && apt-get install -y \
    build-essential libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

# Default command: Gunicorn with Uvicorn ASGI workers.
# WebSocket still works because Channels uses the Redis channel layer.
# Overridden in docker-compose for celery/beat.
CMD gunicorn config.asgi:application -w 4 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8000 --timeout 300 --graceful-timeout 30 --access-logfile -
