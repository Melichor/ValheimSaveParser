#!/usr/bin/env python3
"""Rewrite the generated achievement lists in achi_hunter.py (CRAFTABLE, BUILDABLE, ENEMIES, BOSSES, TROPHIES,
CRAFTABLE_WEAPONS, COOKED_FOOD, MINIBOSSES, FISH) from the game files.

Developer tool. It reads raw.json, which tools/extract_game_data.py writes, so it needs no game files itself:

    python3 tools/extract_game_data.py --game "<path to steamapps/common/Valheim>" --out data
    python3 tools/update_achievement_lists.py data/raw.json            # rewrite the block
    python3 tools/update_achievement_lists.py data/raw.json --check    # only show what would change

The dynamic lists follow the game's own code (Achievements.Initialize and ObjectDB in assembly_valheim.dll, 1.0.21):
  * AllItemCraft: every recipe in the item database that has a crafting station, minus the excluded items.
  * AllWeaponCraft: every recipe whose item is a weapon (one-handed, two-handed, bow, torch), minus excluded items.
  * AllFoodCooked: every recipe for an item with food value, plus every food a cooking station produces.
  * AllBuildPieces: every piece of every build table (carried by an item) that allows removing pieces, except
    repair pieces. Hidden and seasonal pieces count.
  * FindAllTrophies: every trophy item, one per name, minus excluded items.
  * KillAllCreatures: every creature flagged "Included", one per name; the bosses are listed separately.
The bosses, mini-bosses and fish are fixed lists in the AllBosses, AllMiniBosses and GrindFish achievements.
"""
import json
import re
import sys
from pathlib import Path

BEGIN = "# BEGIN GENERATED ACHIEVEMENT LISTS"
END = "# END GENERATED ACHIEVEMENT LISTS"
WEAPON_TYPES = {3, 4, 14, 15, 22}   # OneHandedWeapon, Bow, TwoHandedWeapon, Torch, TwoHandedWeaponLeft
TROPHY, CONSUMABLE, INCLUDED = 13, 2, 1


def build(raw, known_names=None):
    """The lists, and any boss that is not flagged Included. `known_names` (token -> name) fills in display names the
    game's localization table lacks."""
    loc, known_names = raw["loc"], known_names or {}

    def shown(token):
        name = loc.get((token or "").lstrip("$"))
        if not name:                                        # missing, or empty (the spirit creatures)
            return known_names.get(token, token)
        return re.sub(r"<[^>]+>", "", name).strip()        # drop rich-text tags like <color=orange>
    items, items_by_go = {}, {}
    for i in raw["items"]:
        items.setdefault(i["pid"], i)
        for k in ("go", "root"):
            items_by_go.setdefault(i[k], i)
    recipes = {r["pid"]: r for r in raw["recipes"]}
    db = raw["objectdb"][0]
    db_recipes = [recipes[p] for p in db["recipes"] if p in recipes]
    db_items = [items_by_go[p] for p in db["items"] if p in items_by_go]
    excluded = [items_by_go[p]["pid"] for a in raw["achievements"] for p in a["itemsExcluded"] if p in items_by_go]

    def minus_excluded(components):
        out = list(components)
        for pid in excluded:                    # List.Remove: only the first occurrence of each excluded item
            if pid in out:
                out.remove(pid)
        return out

    def table(pids):
        return {items[p]["token"]: shown(items[p]["token"]) for p in pids if items[p]["token"]}

    craft = minus_excluded(r["item"] for r in db_recipes
                           if r["item"] in items and items[r["item"]]["token"] and r["station"])
    weapons = minus_excluded(r["item"] for r in db_recipes
                             if r["item"] in items and items[r["item"]]["type"] in WEAPON_TYPES)
    food = [r["item"] for r in db_recipes if r["item"] in items and (items[r["item"]]["food"] or 0) > 0]
    for c in raw["conversions"]:
        if c["how"] != "cooking":
            continue
        for step in c["list"]:
            to = items.get(step["to"])
            if to and (to["food"] or 0) > 0 and to["type"] == CONSUMABLE and to["pid"] not in food:
                food.append(to["pid"])

    trophies, seen = [], set()
    for i in db_items:
        if i["type"] == TROPHY and i["token"] not in seen:
            seen.add(i["token"])
            trophies.append(i["pid"])
    trophies = minus_excluded(trophies)

    tables = {t["pid"]: t for t in raw["piecetables"]}
    tables_by_go = {}
    for t in raw["piecetables"]:
        for k in ("go", "root"):
            tables_by_go.setdefault(t[k], t)
    pieces_by_go = {}
    for p in raw["pieces"]:
        for k in ("go", "root"):
            pieces_by_go.setdefault(p[k], p)
    pieces = {}
    for i in db_items:
        t = tables.get(i["bp"]) or tables_by_go.get(i["bp"])
        if not t or not t["can"]:
            continue
        for g in t["pieces"]:
            p = pieces_by_go.get(g)
            if p and not p["repair"] and p["token"]:
                pieces.setdefault(p["token"], shown(p["token"]))

    defs = {a["id"]: a for a in raw["achievementdefs"]}
    boss_tokens = [t for t, _ in defs["AllBosses"]["enemies"]]
    creatures = {}
    for c in raw["characters"]:
        if c["achievement"] == INCLUDED and c["token"]:
            creatures.setdefault(c["token"], shown(c["token"]))
    return {
        "CRAFTABLE": dict(sorted(table(craft).items())),
        "BUILDABLE": dict(sorted(pieces.items())),
        "ENEMIES": dict(sorted((t, n) for t, n in creatures.items() if t not in boss_tokens)),
        "BOSSES": {t: shown(t) for t in boss_tokens},
        "TROPHIES": dict(sorted(table(trophies).items())),
        "CRAFTABLE_WEAPONS": dict(sorted(table(weapons).items())),
        "COOKED_FOOD": dict(sorted(table(food).items())),
        "MINIBOSSES": {t: shown(t) for t, _ in defs["AllMiniBosses"]["enemies"]},
        "FISH": {t: shown(t) for t in defs["GrindFish"]["pickables"]},
    }, sorted(t for t in boss_tokens if t not in creatures)


COMMENTS = {
    "CRAFTABLE": "# AllItemCraft: every recipe that needs a crafting station, minus the items the game excludes.\n"
                 "# Station-less hand recipes (stone axe, club, ...), cooked food and smelting do not count here.",
    "BUILDABLE": "# AllBuildPieces: every piece in a build table that allows removing pieces (Hammer), except the repair tool.\n"
                 "# Cultivator and Hoe pieces do not count. Hidden/seasonal pieces do.",
    "ENEMIES": "# KillAllCreatures / KillAllCreaturesHard: every character the game flags as \"killed for achievements\",\n"
               "# bosses split out into BOSSES below (the game lists them together).",
    "BOSSES": "# AllBosses / AllBossesNormal / AllBossesHard (identical list; Frozen King counts via its phase 3 form)",
    "TROPHIES": "# FindAllTrophies: every trophy item (one per name) minus excluded ones. Counted from the item pick-up stats.",
    "CRAFTABLE_WEAPONS": "# AllWeaponCraft: every weapon (1h, 2h, bows, torches) with a recipe, minus excluded items. "
                         "Hand recipes with no station count here.",
    "COOKED_FOOD": "# AllFoodCooked: every food with a recipe, plus every food a cooking station/oven can produce.",
    "MINIBOSSES": "# AllMiniBosses (any difficulty): the fixed list in the AllMiniBosses achievement",
    "FISH": "# GrindFish: every fish species must be caught (reeled in) once. Counted in the pickables table, "
            "not by picking the fish up.",
}


def render(lists):
    lines = [BEGIN + " (tools/update_achievement_lists.py rewrites everything up to END GENERATED ACHIEVEMENT LISTS)"]
    for name, table in lists.items():
        lines += ["", COMMENTS[name], f"{name} = {{"] + [f"    {k!r}: {v!r}," for k, v in table.items()] + ["}"]
    return "\n".join(lines + ["", END])


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) != 1:
        sys.exit(__doc__)
    target = Path(__file__).resolve().parent.parent / "achi_hunter.py"
    text = target.read_text()
    namespace = {}
    exec(compile(text, "achi_hunter", "exec"), namespace)   # noqa: S102  (the current lists, for names and --check)
    known = {k: v for name in COMMENTS for k, v in namespace.get(name, {}).items()}
    lists, missing_bosses = build(json.loads(Path(args[0]).read_text()), known)
    if missing_bosses:
        print("warning: bosses not flagged Included:", missing_bosses)
    if "--check" in sys.argv:
        for name, table in lists.items():
            old = namespace[name]
            added, removed = sorted(set(table) - set(old)), sorted(set(old) - set(table))
            renamed = sorted(k for k in table if k in old and table[k] != old[k])
            print(f"{name}: {len(old)} -> {len(table)}" + (f"; added {added}" if added else "")
                  + (f"; removed {removed}" if removed else "") + (f"; renamed {[(k, old[k], table[k]) for k in renamed]}" if renamed else ""))
        return
    block = render(lists)
    if BEGIN in text:
        new = re.sub(re.escape(BEGIN) + r".*?" + re.escape(END), lambda m: block, text, flags=re.S)
    else:                                       # first run: replace the hand-made lists from CRAFTABLE to FISH
        start = text.index("# AllItemCraft:")
        end = text.index("\n}\n", text.index("FISH = {")) + 3
        new = text[:start] + block + "\n" + text[end:]
    target.write_text(new)
    print(", ".join(f"{n} {len(t)}" for n, t in lists.items()))


if __name__ == "__main__":
    main()
