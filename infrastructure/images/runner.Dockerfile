# the runner: reads /config/run.yaml, does the run, writes artifacts.
# git for worktrees, postgres client for seeds and checks, node for the
# claude CLI the Agent SDK drives. build from the repo root:
#   docker build -f infrastructure/images/runner.Dockerfile .
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        git openssh-client postgresql-client curl ca-certificates \
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
