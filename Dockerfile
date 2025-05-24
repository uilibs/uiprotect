FROM python:3.13-slim-bookworm AS base

LABEL org.opencontainers.image.source https://github.com/uilibs/uiprotect

ENV PYTHONUNBUFFERED 1
ENV UV_SYSTEM_PYTHON true
ARG TARGETPLATFORM

RUN addgroup --system --gid 1000 app \
    && adduser --system --shell /bin/bash --uid 1000 --home /home/app --ingroup app app

RUN --mount=type=cache,mode=0755,id=apt-$TARGETPLATFORM,target=/var/lib/apt/lists \
    apt-get update -qq \
    && apt-get install -yqq ffmpeg


FROM base AS builder

RUN --mount=type=cache,mode=0755,id=apt-$TARGETPLATFORM,target=/var/lib/apt/lists \
    apt-get update -qq \
    && apt-get install -yqq build-essential git

RUN --mount=type=cache,mode=0755,id=pip-$TARGETPLATFORM,target=/root/.cache \
    pip install --root-user-action=ignore -U pip uv poetry

FROM builder AS prod-builder

ARG UIPROTECT_VERSION

WORKDIR /tmp/build
COPY pyproject.toml poetry.lock ./
RUN --mount=type=cache,mode=0755,id=pip-$TARGETPLATFORM,target=/root/.cache \
    poetry config virtualenvs.create false \
    && poetry install --only main --no-root --no-interaction --no-ansi

COPY . .
RUN --mount=type=cache,mode=0755,id=pip-$TARGETPLATFORM,target=/root/.cache \
    SETUPTOOLS_SCM_PRETEND_VERSION=${UIPROTECT_VERSION} poetry build -f wheel

FROM base AS prod

ARG UIPROTECT_VERSION

COPY --from=builder /usr/local/bin/uv /usr/local/bin/
COPY --from=prod-builder /tmp/build/dist/*.whl /tmp/
RUN --mount=type=cache,mode=0755,id=pip-$TARGETPLATFORM,target=/root/.cache \
    uv pip install -U /tmp/*.whl \
    && rm /tmp/*.whl

COPY .docker/entrypoint.sh /usr/local/bin/entrypoint
RUN chmod +x /usr/local/bin/entrypoint \
    && mkdir /data \
    && chown app:app /data

USER app
VOLUME /data
WORKDIR /data
ENTRYPOINT ["/usr/local/bin/entrypoint"]


FROM builder AS builder-dev

WORKDIR /workspaces/uiprotect
COPY pyproject.toml poetry.lock ./
RUN --mount=type=cache,mode=0755,id=pip-$TARGETPLATFORM,target=/root/.cache \
    poetry config virtualenvs.create false \
    && poetry install --with dev --no-root --no-interaction --no-ansi

FROM base AS dev

# Python will not automatically write .pyc files
ENV PYTHONDONTWRITEBYTECODE 1
# Enables Python development mode, see https://docs.python.org/3/library/devmode.html
ENV PYTHONDEVMODE 1

COPY --from=builder-dev /usr/local/bin/ /usr/local/bin/
COPY --from=builder-dev /usr/local/lib/python3.13/ /usr/local/lib/python3.13/
COPY ./.docker/docker-fix.sh /usr/local/bin/docker-fix
COPY ./.docker/bashrc /root/.bashrc
COPY ./.docker/bashrc /home/app/.bashrc
RUN --mount=type=cache,mode=0755,id=apt-$TARGETPLATFORM,target=/var/lib/apt/lists \
    apt-get update -qq \
    && apt-get install -yqq git curl vim procps curl jq sudo \
    && echo 'app ALL=(ALL) NOPASSWD: ALL' >> /etc/sudoers \
    && chown app:app /home/app/.bashrc \
    && chmod +x /usr/local/bin/docker-fix

ENV PYTHONPATH /workspaces/uiprotect/
ENV PATH $PATH:/workspaces/uiprotect/.bin
USER app
WORKDIR /workspaces/uiprotect/
