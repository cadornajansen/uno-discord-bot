# syntax=docker/dockerfile:1

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

COPY pyproject.toml ./

RUN --mount=type=cache,target=/root/.cache/pip \
    python - <<'PY'
import subprocess
import sys
import tomllib

with open("pyproject.toml", "rb") as pyproject_file:
    dependencies = tomllib.load(pyproject_file)["project"]["dependencies"]

subprocess.check_call(
    [sys.executable, "-m", "pip", "install", *dependencies]
)
PY

RUN useradd --create-home --uid 10001 uno \
    && mkdir -p /app/logs \
    && chown uno:uno /app/logs

COPY --chown=uno:uno README.md main.py ./
COPY --chown=uno:uno bot ./bot
COPY --chown=uno:uno config ./config
COPY --chown=uno:uno scripts ./scripts
COPY --chown=uno:uno data ./data

USER uno

CMD ["python", "main.py"]
