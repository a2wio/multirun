#!/usr/bin/env bash
# the point of this task is eight pages side by side, and the tree the
# page was written in is deleted at teardown. So the page is copied out
# next to the run's other artifacts, where the PVC keeps it: the
# comparison becomes `ls */page.html` instead of patch surgery.
#
# The artifact dir is only knowable from the rendered run.yaml, which
# exists in-cluster. Locally there is nothing to copy to and that is
# fine — the file is already on disk where it was written.
set -euo pipefail
page=article/index.html
test -f "$page"

run_yaml=${RUN_CONFIG:-/config/run.yaml}
[ -f "$run_yaml" ] || exit 0

out=$(sed -n 's/^artifact_dir:[[:space:]]*//p' "$run_yaml" | head -1)
[ -n "$out" ] || exit 0

mkdir -p "$out"
cp "$page" "$out/page.html"
test -s "$out/page.html"
