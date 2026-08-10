FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        libglib2.0-0 \
        libgl1 \
        libgomp1 \
        libxcb1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml README.md ./
COPY bot ./bot
COPY config ./config
COPY scripts ./scripts
COPY data ./data
COPY main.py ./main.py

RUN pip install --no-cache-dir . \
    && useradd --create-home --uid 10001 uno \
    && mkdir -p /app/logs \
    && chown -R uno:uno /app

USER uno

CMD ["python", "main.py"]
