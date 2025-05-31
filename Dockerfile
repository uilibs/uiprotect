FROM python:3.12-slim

# System-abhängige Abhängigkeiten installieren
RUN apt-get update && apt-get install -y \
    curl \
    git \
    ffmpeg \
    build-essential \
 && rm -rf /var/lib/apt/lists/*

# Poetry installieren (Version 2.1.3)
RUN curl -sSL https://install.python-poetry.org | POETRY_VERSION=2.1.3 python3 -

# Poetry zu PATH hinzufügen
ENV PATH="/root/.local/bin:${PATH}"

# Arbeitsverzeichnis erstellen und setzen
WORKDIR /workspace

# Virtuelle Umgebungen deaktivieren, Poetry wird die Umgebungen verwalten
ENV POETRY_VIRTUALENVS_CREATE=false

# Installiere Projekt-Abhängigkeiten, falls pyproject.toml vorhanden ist
COPY pyproject.toml poetry.lock* ./
RUN poetry install --no-root || true
