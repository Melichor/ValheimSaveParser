#!/usr/bin/env python3
"""Rewrite the generated block of upgrade_cost.py: every item the Forge of Potential can upgrade, with its recipe.

Developer tool. It reads raw.json, which tools/extract_game_data.py writes, so it needs no game files itself:

    python3 tools/extract_game_data.py --game "<path to steamapps/common/Valheim>" --out data
    python3 tools/update_cost_data.py data/raw.json

An item is included when the Forge would list it: its recipe has an upgrader ingredient (an Idol), the item has more
than one quality level, and the recipe is enabled or belongs to a season (then it is only available during that season).
For each item the block keeps its crafting station, the highest quality that station can reach, and every ingredient.
Gear used as an ingredient (the Nord Sword in a Frostfire Sword) is costed as what it takes to craft, recursively.

Some items (Deep North gear and staffs) have an upgrade-only recipe: they are crafted as a cast instead, which a foundry
cooks into the item. For those, the cost of a new copy comes from the cast recipe plus the foundry's fuel, while upgrades
and break refunds still use the upgrade recipe, as in the game.
"""
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

BEGIN = "# BEGIN GENERATED COST DATA"
END = "# END GENERATED COST DATA"


def build(raw, seasons):
    loc = raw["loc"]
    items = {}
    for i in raw["items"]:
        items.setdefault(i["pid"], i)

    def name(token):
        # display names like "$item_upgrader_tier7 $item_upgrader_weapon $item_upgrader_name" are several tokens
        return " ".join(loc.get(t.lstrip("$"), t) for t in (token or "").split())

    stations = {s["pid"]: s for s in raw["stations"]}
    # a station's highest level is 1 + one per kind of extension that can be built with the hammer
    hammer = set(max(raw["piecetables"], key=lambda t: len(t["pieces"]))["pieces"])
    extensions = defaultdict(set)
    for e in raw["extensions"]:
        s = stations.get(e["station"])
        if s and e["root"] in hammer:
            if e["stack"]:
                sys.exit(f"stackable extension {e['rootName']}: the station level would be unlimited")
            extensions[s["token"]].add(e["rootName"])

    # foundry conversions: cast item -> (finished item, station name, fuel item name, fuel per cast)
    cooked = {}
    for c in raw["conversions"]:
        if not c.get("useFuel") or not c.get("secPerFuel") or c.get("fuel") not in items:
            continue
        for step in c["list"]:
            if step["from"] in items and step["to"] in items:
                per = step["time"] / c["secPerFuel"]
                cooked[items[step["from"]]["rootName"]] = (items[step["to"]]["rootName"], name(c["name"]),
                                                          name(items[c["fuel"]]["token"]), int(per) if per == int(per) else per)
    craft_recipes = {}                          # item root name -> its craftable recipe (shown in the craft tab)
    for r in raw["recipes"]:
        if r["item"] in items and r.get("enabled") and not r.get("upgradeOnly"):
            craft_recipes.setdefault(items[r["item"]]["rootName"], r)

    def craft_of(root, seen=()):
        """What one new item costs to craft: [(ingredient, amount, part)] and its cast route (or None).

        Gear used as an ingredient (a Nord Sword in a Frostfire Sword) is replaced by what it takes to craft, recursively;
        `part` then names that gear, and is None for the item's own ingredients."""
        recipe, via, fuel = craft_recipes.get(root), None, []
        if recipe is None:                      # an upgrade-only item: crafted as a cast, cooked in a foundry
            casts = [cast for cast, made in cooked.items() if made[0] == root and cast in craft_recipes]
            if len(casts) != 1:
                return None, None
            recipe = craft_recipes[casts[0]]
            _, foundry, fuel_name, per_cast = cooked[casts[0]]
            via = {"cast": name(items[recipe["item"]]["token"]), "foundry": foundry, "fuel": fuel_name,
                   "perCast": per_cast}
            fuel = [(fuel_name, per_cast, None)]
        out = []
        for x in recipe["resources"]:
            if x["item"] not in items or x["upgrader"]:
                continue
            sub = items[x["item"]]
            label = name(sub["token"])
            if (sub.get("maxQuality") or 1) > 1 and sub["rootName"] not in seen:
                inner, _ = craft_of(sub["rootName"], seen + (root,))
                if inner is not None:
                    out += [(n, a * x["amount"], part or label) for n, a, part in inner]
                    continue
            out.append((label, x["amount"], None))
        return out + fuel, via

    in_season = {}
    for season in seasons:
        for pid in season["recipes"]:
            in_season[pid] = season["name"]

    out, odds = {}, set()
    for r in raw["recipes"]:
        it = items.get(r["item"])
        if not it or (it.get("maxQuality") or 1) <= 1:
            continue
        upgraders = [x for x in r["resources"] if x["upgrader"]]
        if not upgraders or not (r.get("enabled") or r["pid"] in in_season):
            continue
        for u in upgraders:
            i = items[u["item"]]
            odds.add((round(i["upgradeChance"], 6), round(i["breakChance"], 6), i["breakReturn"]))
        station = stations.get(r["station"])
        top = 1 + len(extensions[station["token"]]) if station else None
        cap = it["maxQuality"] if not station else min(it["maxQuality"], top - max(1, r["minLevel"] or 1) + 1)
        resources = [(name(items[x["item"]]["token"]), x["amount"], x["perLevel"], bool(x["upgrader"]),
                      bool(x["recover"])) for x in r["resources"] if x["item"] in items]
        # what one new copy costs (the cast and its fuel for an upgrade-only item, gear ingredients expanded)
        craft, via = craft_of(it["rootName"])
        if craft is None:                       # e.g. a seasonal recipe, which the craft-recipe list leaves out
            craft = [(x[0], x[1], None) for x in resources if not x[3]]
        listed = {x[0] for x in resources}
        fuel_name = via["fuel"] if via else None
        # a break refunds from the upgrade recipe; own ingredients it does not list are never returned
        not_refunded = [n for n, _, part in craft if part is None and n not in listed and n != fuel_name]
        expanded = {part for _, _, part in craft if part}
        never = [f"{x[0]} and everything crafted into it" if x[0] in expanded else x[0]
                 for x in resources if not x[3] and not x[4]]
        never += ([fuel_name] if fuel_name else []) + not_refunded + [x[0] for x in resources if x[3]]
        out[it["rootName"]] = {
            "name": name(it["token"]),
            "station": name(station["token"]) if station else None,
            "minStationLevel": max(1, r["minLevel"] or 1),
            "stationMaxLevel": top,
            "maxQuality": it["maxQuality"],
            "cap": cap,
            "season": in_season.get(r["pid"]),
            # (ingredient, amount, amount per level, is the Idol, refunded in part when the item breaks)
            "resources": resources,
            "craft": craft,             # what one new copy costs: (ingredient, amount, gear it is for, or None)
            "via": via,                 # the cast and foundry it is made through, or None
            "notRefunded": not_refunded,    # own ingredients the upgrade recipe leaves out: a break never returns them
            "neverRefunded": never,     # everything a break never gives back, for the report
        }
    if len(odds) != 1:
        sys.exit(f"the upgrader items do not all have the same odds: {sorted(odds)}")
    return out, odds.pop()


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    raw = json.loads(Path(sys.argv[1]).read_text())
    if "seasons" not in raw:
        sys.exit("raw.json has no seasons: rescan the game with tools/extract_game_data.py --rescan")
    seasons = raw["seasons"]
    data, (_, _, refund) = build(raw, seasons)
    lines = [BEGIN + " (tools/update_cost_data.py rewrites everything up to END GENERATED COST DATA)",
             "# Share of the ingredients (those marked refundable) returned when the Forge of Potential breaks an item.",
             f"BREAK_RETURN = {refund!r}",
             "# Prefab name -> recipe facts. resources: the recipe used for upgrades and break refunds, as (ingredient,",
             "# amount, amount per level, is the Idol, refundable). craft: what one new copy costs, as (ingredient, amount,",
             "# the gear ingredient it goes into or None); gear ingredients are replaced by what they take to craft.",
             "ITEMS = {"]
    for k in sorted(data):
        lines.append(f"    {k!r}: {data[k]!r},")
    lines += ["}", END]
    target = Path(__file__).resolve().parent.parent / "upgrade_cost.py"
    text = target.read_text()
    new = re.sub(re.escape(BEGIN) + r".*?" + re.escape(END), lambda m: "\n".join(lines), text, flags=re.S)
    if new == text and "\n".join(lines) not in text:
        sys.exit("generated block markers not found in upgrade_cost.py")
    target.write_text(new)
    capped = sum(1 for v in data.values() if v["cap"] < v["maxQuality"])
    casts = sum(1 for v in data.values() if v["via"])
    print(f"{len(data)} items, break refund {refund}, {capped} capped below their max quality by their station, "
          f"{casts} crafted through a cast")


if __name__ == "__main__":
    main()
