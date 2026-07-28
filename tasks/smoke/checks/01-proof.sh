#!/usr/bin/env bash
# the agent claims it wrote PROOF.md; believe files, not claims
set -euo pipefail
test -s PROOF.md
