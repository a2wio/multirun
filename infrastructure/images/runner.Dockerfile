# the runner: reads /config/run.yaml, does the run, writes artifacts.
# git for worktrees, postgres client for seeds and checks, node for the
# claude CLI the Agent SDK drives. build from the repo root:
#   docker build -f infrastructure/images/runner.Dockerfile .
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
RUN pip install --no-cache-dir .

# subscription creds mount at /home/agent/.claude (Secret: claude-creds);
# no ANTHROPIC_API_KEY, here or anywhere
RUN useradd -m -u 1000 agent
USER agent
ENV HOME=/home/agent

ENTRYPOINT ["multirun-runner"]
CMD ["/config/run.yaml"]

ENV PYTHONUNBUFFERED=1
