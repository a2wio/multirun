# core: the controller. Talks to the k8s api (spawn jobs) and the Neon
# api (branches); carries the claude CLI only to exercise credential
# refresh. build from the repo root:
#   docker build -f infrastructure/images/core.Dockerfile .
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        git postgresql-client curl ca-certificates \
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
