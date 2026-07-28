#!/usr/bin/env bash
# whatever the agent decided, the app still has to build
set -euo pipefail
npm ci --no-audit --no-fund
npm run build
