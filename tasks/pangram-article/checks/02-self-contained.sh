#!/usr/bin/env bash
# the page renders alone in an iframe or the side-by-side is a wall of
# broken boxes. So: every src/href either leaves the machine (fonts),
# is inline (data:), is an anchor — or it is a local file that must
# actually exist next to the page.
set -euo pipefail
page=article/index.html
dir=$(dirname "$page")

missing=()
while IFS= read -r ref; do
    case "$ref" in
        http://*|https://*|//*|data:*|"#"*|mailto:*|tel:*|"") continue ;;
    esac
    target=${ref%%[?#]*}
    [ -e "$dir/$target" ] || [ -e "$target" ] || missing+=("$ref")
done < <(grep -oE '(src|href)="[^"]*"' "$page" | sed -E 's/^[a-z]+="//; s/"$//')

if [ ${#missing[@]} -gt 0 ]; then
    printf 'page references local files that do not exist: %s\n' "${missing[*]}" >&2
    exit 1
fi
