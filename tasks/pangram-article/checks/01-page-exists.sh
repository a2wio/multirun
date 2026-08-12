#!/usr/bin/env bash
# a page, not a stub: the file is where it was asked for, it is a whole
# html document, and it has enough in it to be an article
set -euo pipefail
page=article/index.html
test -f "$page"
bytes=$(wc -c < "$page")
[ "$bytes" -ge 4000 ]
grep -qi '<html' "$page"
grep -qi '</html>' "$page"
grep -qi '<style' "$page"
