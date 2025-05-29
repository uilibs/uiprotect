# syntax=docker/dockerfile:1
FROM python:3.13-slim-bookworm

LABEL org.opencontainers.image.source=https://github.com/uilibs/uiprotect

RUN addgroup --system --gid 1000 app \
    && adduser --system --shell /bin/bash --uid 1000 --home /home/app --ingroup app app

RUN apt-get update -qq \
    && apt-get install -yqq --no-install-recommends \
        ffmpeg \
        git \
        curl \
        build-essential \
        vim \
        procps \
        jq \
        sudo \
    && rm -rf /var/lib/apt/lists/*

ENV POETRY_HOME=/usr/local
RUN curl -sSL https://install.python-poetry.org | python3 - --version 1.8.2

WORKDIR /workspaces/uiprotect
COPY pyproject.toml poetry.lock ./
RUN poetry config virtualenvs.create false

COPY . .

RUN poetry install --no-interaction --no-ansi

RUN if [ -f /workspaces/uiprotect/src/uiprotect/cli/app.py ] || [ -f /workspaces/uiprotect/src/uiprotect/cli.py ]; then \
      mkdir -p /home/app/.bash_completions && \
      poetry run uiprotect --install-completion bash > /home/app/.bash_completions/uiprotect.sh || true; \
    fi

RUN chown -R app:app /workspaces/uiprotect /home/app
USER app
ENV PATH="/home/app/.local/bin:$PATH"
ENV PYTHONPATH=/workspaces/uiprotect
WORKDIR /workspaces/uiprotect

CMD ["bash"]
