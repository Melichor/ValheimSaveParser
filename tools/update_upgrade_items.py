#!/usr/bin/env python3
"""Rewrite the generated block of upgrade_oracle.py (the items that can be upgraded, and the upgrader's odds).

Developer tool. It reads raw.json, which tools/extract_game_data.py writes, so it needs no game files itself:

    python3 tools/extract_game_data.py --game "<path to steamapps/common/Valheim>" --out data
    python3 tools/update_upgrade_items.py data/raw.json

An item can be upgraded at the upgrade station when its recipe has an upgrader ingredient (the Upgrader0Armor,
Upgrader3Weapon, ... items). Every upgrader item must have the same odds, because the script uses one pair of numbers.
"""
import json
import re
import sys
from pathlib import Path

BEGIN = "# BEGIN GENERATED UPGRADABLE"
END = "# END GENERATED UPGRADABLE"


def build(raw):
    items = {}
    for i in raw["items"]:
        items.setdefault(i["pid"], i)
    names, odds = {}, set()
    for r in raw["recipes"]:
        upgraders = [x for x in r["resources"] if x["upgrader"]]
        if not upgraders or r["item"] not in items:
            continue
        for u in upgraders:
            i = items[u["item"]]
            odds.add((round(i["upgradeChance"], 6), round(i["breakChance"], 6)))
        item = items[r["item"]]
        token = (item["token"] or "").lstrip("$")
        names[item["rootName"]] = raw["loc"].get(token) or token
    if len(odds) != 1:
        sys.exit(f"the upgrader items do not all have the same odds: {sorted(odds)}")
    return names, odds.pop()


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    names, (upgrade, brk) = build(json.loads(Path(sys.argv[1]).read_text()))
    lines = [BEGIN + " (tools/update_upgrade_items.py rewrites everything up to END GENERATED UPGRADABLE)",
             "# Chance that one upgrade attempt succeeds, and the chance (checked next) that a failed attempt destroys the item.",
             f"UPGRADE_CHANCE = {upgrade!r}",
             f"BREAK_CHANCE = {brk!r}",
             "# Prefab name -> display name of every item that can be upgraded at the upgrade station.",
             "UPGRADABLE = {"]
    lines += [f"    {k!r}: {names[k]!r}," for k in sorted(names)]
    lines += ["}", END]
    target = Path(__file__).resolve().parent.parent / "upgrade_oracle.py"
    text = target.read_text()
    new = re.sub(re.escape(BEGIN) + r".*?" + re.escape(END), lambda m: "\n".join(lines), text, flags=re.S)
    if new == text and "\n".join(lines) not in text:
        sys.exit("generated block markers not found in upgrade_oracle.py")
    target.write_text(new)
    print(f"{len(names)} upgradable items, upgrade chance {upgrade}, break chance {brk}")


if __name__ == "__main__":
    main()
