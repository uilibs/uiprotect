FROM python:3.13-slim

RUN apt-get update && apt-get install -y \
    curl \
    git \
    ffmpeg \
    build-essential \
    bash \
 && rm -rf /var/lib/apt/lists/*

SHELL ["/bin/bash", "-c"]

RUN curl -sSL https://install.python-poetry.org | POETRY_VERSION=2.1.3 python3 -

ENV PATH="/root/.local/bin:${PATH}"

WORKDIR /workspace

ENV POETRY_VIRTUALENVS_CREATE=false

COPY pyproject.toml poetry.lock* ./
RUN poetry install --no-root || true
