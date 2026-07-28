# core: the controller. Talks to the k8s api (spawn jobs) and the Neon
# api (branches); carries the claude CLI only to exercise credential
# refresh. build from the repo root:
#   docker build -f infrastructure/images/core.Dockerfile .
FROM python:3.12-slim

# postgres client 17 from pgdg: neon runs 17, and pg_dump refuses newer
# majors — the schema diff should be the full dump, not the fallback
RUN apt-get update && apt-get install -y --no-install-recommends \
        git curl ca-certificates \
    && install -d /usr/share/postgresql-common/pgdg \
    && curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc \
         -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc \
    && echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] http://apt.postgresql.org/pub/repos/apt bookworm-pgdg main" \
         > /etc/apt/sources.list.d/pgdg.list \
    && apt-get update && apt-get install -y --no-install-recommends postgresql-client-17 \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && npm install -g @anthropic-ai/claude-code \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY core/ /app/
# tasks ride along so the in-cluster controller can resolve a fanout's
# task dir (task.md, checks, seeds) without any volume gymnastics
COPY tasks/ /app/tasks/
RUN pip install --no-cache-dir ".[k8s,results]"

RUN useradd -m -u 1000 core
USER core
ENV HOME=/home/core

ENTRYPOINT ["multirun"]

ENV PYTHONUNBUFFERED=1
