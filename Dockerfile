FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./
COPY scripts ./scripts
COPY docker ./docker

# Install as root, then drop to a dedicated non-root user (F-05).
# UID/GID 10001 is stable across rebuilds for volume permission expectations.
RUN pip install --upgrade pip \
    && pip install . \
    && chmod +x /app/docker/entrypoint-api.sh /app/docker/entrypoint-bot.sh \
      /app/docker/entrypoint-migrate.sh \
    && groupadd --system --gid 10001 onboard \
    && useradd --system --uid 10001 --gid onboard --home-dir /app --shell /usr/sbin/nologin onboard \
    && chown -R onboard:onboard /app

USER onboard

EXPOSE 8000 8081

CMD ["/app/docker/entrypoint-api.sh"]
