#!/usr/bin/env python3
"""Write the earliest biome of every listed item into achi_hunter.py.

Run it after tools/extract_game_data.py has produced data/biomes.json:
    python3 tools/update_script_biomes.py
It replaces the block between "BEGIN GENERATED BIOMES" and "END GENERATED BIOMES" in achi_hunter.py.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import achi_hunter as H  # noqa: E402

biomes = json.loads((ROOT / "data" / "biomes.json").read_text())
wanted = {
    "BIOME_CRAFT": ("craft", set(H.CRAFTABLE) | set(H.CRAFTABLE_WEAPONS) | set(H.COOKED_FOOD)),
    "BIOME_PIECE": ("piece", set(H.BUILDABLE)),
    "BIOME_FOUND": ("found", set(H.TROPHIES) | set(H.FISH)),
    "BIOME_CREATURE": ("creature", set(H.ENEMIES) | set(H.BOSSES) | set(H.MINIBOSSES)),
}
order = biomes["order"]
lines = ["# BEGIN GENERATED BIOMES (tools/update_script_biomes.py rewrites everything up to END GENERATED BIOMES)",
         "# Earliest biome per token, in progression order below. Craft = where the item can be made, Piece = where a build",
         "# piece can be built, Found = where a trophy or fish can be obtained, Creature = where a creature lives.",
         f"BIOME_ORDER = {order!r}"]
counts = {}
for name, (key, tokens) in wanted.items():
    entries = {t: biomes[key][t] for t in sorted(tokens) if biomes[key].get(t)}
    counts[name] = len(entries)
    lines.append(f"{name} = {{")
    lines += [f"    {t!r}: {b!r}," for t, b in entries.items()]
    lines.append("}")
lines.append("# END GENERATED BIOMES")
path = ROOT / "achi_hunter.py"
text = path.read_text(encoding="utf-8")
new, n = re.subn(r"# BEGIN GENERATED BIOMES.*?# END GENERATED BIOMES", lambda m: "\n".join(lines), text, count=1, flags=re.S)
assert n == 1, "markers not found in achi_hunter.py"
path.write_text(new, encoding="utf-8")
print("wrote", counts)
