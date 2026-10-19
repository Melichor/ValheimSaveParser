#!/usr/bin/env python3
"""Rewrite the generated block of drop_counters.py: every creature's drops, with their chance and whether stars raise it,
and the most stars the creature can have.

Developer tool. The drop flags it needs (does a star raise the chance) are not in raw.json, so it scans the game's asset
bundles itself. It needs UnityPy (pip install UnityPy) and a local Valheim install, and takes a minute or two:

    python3 tools/update_drop_data.py --game "<path to steamapps/common/Valheim>"

A creature's drops are the list in the CharacterDrop component of its prefab (not of the copies placed inside locations).
Every entry is kept, including the drops that always happen, so the script can tell what kind of roll each one is.

A creature's stars come from whatever spawns it, as Character.SetLevel is only called there: the world's spawn lists,
raids and alternate biomes (SpawnSystem), nests (SpawnArea), the spawn points of locations and dungeons (CreatureSpawner,
whose range the location around it can override), TriggerSpawner and SpawnAbility. Offspring, hatched eggs and grown
young take their parent's level (Procreation, EggGrow, Growup). A creature that nothing levels up, like a boss summoned at
its altar, never has stars.
"""
import argparse
import glob
import os
import re
import struct
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from extract_game_data import pp, read_localization, transform_info  # noqa: E402

BEGIN = "# BEGIN GENERATED DROPS"
END = "# END GENERATED DROPS"
# test prefabs that never turn up in normal play; their drops share counters with real creatures (Coins with the Fulings,
# the Draugr Trophy with the Draugr), so they would only clutter those lists
HIDDEN = {"DvergerTest", "TrainingDummy"}


def f32(x):
    return struct.unpack("<f", struct.pack("<f", x))[0]


def float_text(x):
    """The shortest decimal that reads back as the same 32-bit float."""
    for digits in range(1, 10):
        s = f"{x:.{digits}g}"
        if f32(float(s)) == f32(x):
            return s
    return repr(x)


def spawn_data(x, out):
    """Every spawn entry (a prefab with a level range) inside a typetree: SpawnSystem's lists, raids and alternate
    biomes, and SpawnArea's prefabs. Disabled entries never spawn."""
    if isinstance(x, dict):
        if "m_prefab" in x and "m_maxLevel" in x and x.get("m_enabled", 1) and pp(x["m_prefab"]):
            out.append((pp(x["m_prefab"]), int(x["m_maxLevel"])))
        for v in x.values():
            spawn_data(v, out)
    elif isinstance(x, list):
        for v in x:
            spawn_data(v, out)


def scan(game_dir, log=print):
    """The drops, names and highest levels of every creature, read from the asset bundles."""
    import UnityPy
    bundles = sorted(glob.glob(os.path.join(game_dir, "valheim_Data", "StreamingAssets", "SoftRef", "Bundles", "*")))
    item_names, item_tokens = {}, {}                  # item game object id -> prefab name; prefab name -> name token
    creatures, creature_tokens, bosses = {}, {}, set()   # creature prefab id -> prefab name; prefab name -> token
    drops = {}                                        # creature prefab name -> [(item id, chance, scales with stars)]
    levels = []                                       # (creature prefab id, highest level a spawner gives it)
    spawners = []                                     # CreatureSpawner: (creature id, max level, location root, group)
    overrides = {}                                    # location root id -> (max level override, excluded groups)
    edges = []                                        # (parent id, offspring id, lowest level): offspring, eggs, young
    t0 = time.time()
    for n, path in enumerate(bundles):
        try:
            env = UnityPy.load(path)
        except Exception:
            continue
        father_of, transform_of, tgo, mbs = {}, {}, {}, []
        for o in env.objects:
            t = o.type.name
            if t in ("Transform", "RectTransform"):
                try:
                    go, father = transform_info(o.get_raw_data())
                except Exception:
                    continue
                transform_of[go] = o.path_id
                tgo[o.path_id] = go
                father_of[o.path_id] = father
            elif t == "MonoBehaviour":
                try:
                    mbs.append(o.read_typetree())
                except Exception:
                    continue

        def root_of(go):
            tr, seen = transform_of.get(go), 0
            while tr and seen < 64:
                f = father_of.get(tr)
                if not f:
                    return tgo.get(tr)
                tr, seen = f, seen + 1
            return go

        named = []                                    # (kind, game object id, value): need the object's name
        for tt in mbs:
            go = pp(tt.get("m_GameObject"))
            if not go:
                continue
            root = root_of(go)
            if "m_itemData" in tt:
                # a drop points at the item prefab's game object, which is the one holding its ItemDrop
                named.append(("item", go, tt["m_itemData"].get("m_shared", {}).get("m_name")))
            elif "m_killedForAchievements" in tt and "m_name" in tt:
                if go == root:                        # the prefab itself, not a copy placed in a location
                    named.append(("creature", go, (tt["m_name"], tt.get("m_boss"))))
            elif "m_drops" in tt and "m_dropMin" not in tt and isinstance(tt["m_drops"], list) and \
                    tt["m_drops"] and isinstance(tt["m_drops"][0], dict) and "m_amountMin" in tt["m_drops"][0]:
                if go == root:
                    named.append(("drops", go, [(pp(d.get("m_prefab")), d.get("m_chance"), d.get("m_levelMultiplier"))
                                                for d in tt["m_drops"]]))
            elif "m_creaturePrefab" in tt and "m_maxLevel" in tt:                       # CreatureSpawner
                if pp(tt["m_creaturePrefab"]):
                    spawners.append((pp(tt["m_creaturePrefab"]), int(tt["m_maxLevel"]), root, tt.get("m_spawnGroupID")))
            elif "m_creaturePrefabs" in tt and "m_maxLevel" in tt:                      # TriggerSpawner
                levels += [(pp(p), int(tt["m_maxLevel"])) for p in tt["m_creaturePrefabs"] if pp(p)]
            elif "m_spawnPrefab" in tt and "m_levelUpSettings" in tt:                   # SpawnAbility
                top = max([s.get("m_setLevel", 1) for s in tt["m_levelUpSettings"] or []] + [1])
                levels += [(pp(p), int(top)) for p in tt["m_spawnPrefab"] or [] if pp(p)]
            elif "m_enemyMaxLevelOverride" in tt:                                       # Location
                overrides[root] = (int(tt["m_enemyMaxLevelOverride"]), set(tt.get("m_excludeEnemyLevelOverrideGroups") or []))
            elif "m_offspring" in tt and "m_minOffspringLevel" in tt:                   # Procreation
                low = int(tt["m_minOffspringLevel"] or 1)
                edges += [(root, pp(tt[k]), low) for k in ("m_offspring", "m_noPartnerOffspring") if pp(tt.get(k))]
            elif "m_grownPrefab" in tt and "m_altGrownPrefabs" in tt:                   # Growup
                grown = [pp(tt["m_grownPrefab"])] + [pp(e.get("m_prefab")) for e in tt["m_altGrownPrefabs"] or []]
                edges += [(root, g, 1) for g in grown if g]
            elif "m_grownPrefab" in tt and "m_requireNearbyFire" in tt:                 # EggGrow: the egg's quality
                if pp(tt["m_grownPrefab"]):
                    edges.append((root, pp(tt["m_grownPrefab"]), 1))
            for key in ("m_spawners", "m_events", "m_prefabs", "m_alts"):              # SpawnSystem, raids, SpawnArea
                if key in tt:
                    spawn_data(tt[key], levels)
        wanted = {go for _, go, _ in named}
        names = {}
        for o in env.objects:
            if o.type.name == "GameObject" and o.path_id in wanted:
                try:
                    names[o.path_id] = o.read_typetree().get("m_Name")
                except Exception:
                    pass
        for kind, go, value in named:
            name = names.get(go)
            if not name:
                continue
            if kind == "item":
                item_names[go] = name
                item_tokens.setdefault(name, value)
            elif kind == "creature":
                creatures[go] = name
                creature_tokens.setdefault(name, value[0])
                if value[1]:
                    bosses.add(name)
            elif name not in drops:
                drops[name] = value
        if n % 100 == 0:
            log(f"  {n}/{len(bundles)} bundles, {int(time.time() - t0)} s")

    # the highest level of each prefab: its spawners, then what it inherits from its parents, until nothing changes
    level = defaultdict(lambda: 1)
    for pid, top, root, group in spawners:
        override, excluded = overrides.get(root, (-1, set()))
        if override >= 0 and group not in excluded:
            top = override
        level[pid] = max(level[pid], top)
    for pid, top in levels:
        level[pid] = max(level[pid], top)
    changed = True
    while changed:
        changed = False
        for parent, child, low in edges:
            if max(low, level[parent]) > level[child]:
                level[child] = max(low, level[parent])
                changed = True
    top_level = defaultdict(lambda: 1)
    for pid, name in creatures.items():
        top_level[name] = max(top_level[name], level[pid])

    # the item references are game object ids; turn them into prefab names now that every bundle has been read
    resolved = {}
    for creature, entries in drops.items():
        if creature in HIDDEN:
            continue
        rows = [(item_names[pid], chance, bool(scales)) for pid, chance, scales in entries
                if pid in item_names and chance is not None]
        if rows:
            resolved[creature] = rows
    stars = {c: top_level[c] - 1 for c in resolved}
    for boss in sorted(bosses & set(resolved)):
        if stars[boss]:
            log(f"  note: the boss {boss} can have {stars[boss]} star(s)")
    return resolved, creature_tokens, item_tokens, stars


def build(drops, creature_tokens, item_tokens, stars, loc):
    def name(token, fallback):
        return loc.get((token or "").lstrip("$")) or fallback

    for prefab in list(drops) + [i for rows in drops.values() for i, _, _ in rows]:
        if "." in prefab:
            sys.exit(f"{prefab!r} has a dot in its name, which drop_counters.py uses to separate the parts of a filter")
    lines = [BEGIN + " (tools/update_drop_data.py rewrites everything up to END GENERATED DROPS)",
             "# Creature prefab -> (display name, most stars it can have, [(item prefab, drop chance, stars raise the",
             "# chance), ...]) from each creature's CharacterDrop. Chances are the game's 32-bit floats, in the fewest digits",
             "# that read back the same. The stars come from the creature's spawners (0: nothing levels it up, like a boss).",
             "DROPS = {"]
    for creature in sorted(drops):
        lines.append(f"    {creature!r}: ({name(creature_tokens.get(creature), creature)!r}, {stars[creature]}, [")
        lines += [f"        ({item!r}, {float_text(chance)}, {scales}),"
                  for item, chance, scales in drops[creature]]
        lines.append("    ]),")
    lines += ["}", "# Item prefab -> display name, for every item in DROPS.", "ITEM_NAMES = {"]
    items = sorted({i for rows in drops.values() for i, _, _ in rows})
    lines += [f"    {i!r}: {name(item_tokens.get(i), i)!r}," for i in items]
    lines += ["}", END]
    return "\n".join(lines), len(items)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--game", required=True, help="path to the Valheim install (the folder containing valheim_Data)")
    args = ap.parse_args()
    drops, creature_tokens, item_tokens, stars = scan(args.game)
    block, item_count = build(drops, creature_tokens, item_tokens, stars, read_localization(args.game))
    target = Path(__file__).resolve().parent.parent / "drop_counters.py"
    text = target.read_text()
    new = re.sub(re.escape(BEGIN) + r".*?" + re.escape(END), lambda m: block, text, flags=re.S)
    if new == text and block not in text:
        sys.exit("generated block markers not found in drop_counters.py")
    target.write_text(new)
    by_stars = defaultdict(int)
    for s in stars.values():
        by_stars[s] += 1
    print(f"{len(drops)} creatures ({', '.join(f'{v} with up to {k} stars' for k, v in sorted(by_stars.items()))}), "
          f"{item_count} items")


if __name__ == "__main__":
    main()
