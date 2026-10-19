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
touch "$out/.nojekyll"                                        # serve the files as they are, without Jekyll
echo "site assembled in $out:"
find "$out" -type f | sort
