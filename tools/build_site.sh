#!/usr/bin/env bash
# Assemble the GitHub Pages site in _site/ (or the folder given as $1): the page and the files it loads at run time.
# Used by .github/workflows/pages.yml and pr-preview.yml. Only these files are published, so save files or game data
# lying around in the checkout never end up on the site.
set -euo pipefail
out="${1:-_site}"
rm -rf "$out"
mkdir -p "$out/web"
cp index.html "$out/"
cp web/*.js web/*.css "$out/web/"
# the root-level scripts the page runs in the browser with Pyodide (achi_hunter.py, upgrade_oracle.py, upgrade_cost.py);
# copied by pattern so a branch that does not have one of them yet still builds
cp ./*.py "$out/"
# stamp the build into the URLs the page loads its own files from (written as file?v=__BUILD__ in index.html and the
# scripts): GitHub Pages lets browsers keep every file for 10 minutes, and a new URL makes them fetch the new one
build="$(git rev-parse --short HEAD 2>/dev/null || date -u +%Y%m%d%H%M%S)"
for f in "$out/index.html" "$out"/web/*.js; do
  sed "s/__BUILD__/$build/g" "$f" > "$f.tmp" && mv "$f.tmp" "$f"
done
touch "$out/.nojekyll"                                        # serve the files as they are, without Jekyll
echo "site assembled in $out:"
find "$out" -type f | sort
