#!/usr/bin/env python3
"""Rewrite the generated block of drop_counters.py: every creature's drops, with their chance and whether stars raise it.

Developer tool. The drop flags it needs (does a star raise the chance) are not in raw.json, so it scans the game's asset
bundles itself. It needs UnityPy (pip install UnityPy) and a local Valheim install, and takes a minute or two:

    python3 tools/update_drop_data.py --game "<path to steamapps/common/Valheim>"

A creature's drops are the list in its CharacterDrop component. Every entry is kept, including the drops that always
happen, so the script can tell what kind of roll each one is.
"""
import argparse
import glob
import os
import re
import struct
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from extract_game_data import pp, read_localization, transform_info  # noqa: E402

BEGIN = "# BEGIN GENERATED DROPS"
END = "# END GENERATED DROPS"


def f32(x):
    return struct.unpack("<f", struct.pack("<f", x))[0]


def float_text(x):
    """The shortest decimal that reads back as the same 32-bit float."""
    for digits in range(1, 10):
        s = f"{x:.{digits}g}"
        if f32(float(s)) == f32(x):
            return s
    return repr(x)


def scan(game_dir, log=print):
    """(creature prefab -> drops, creature prefab -> name token, item prefab -> name token) from the asset bundles."""
    import UnityPy
    bundles = sorted(glob.glob(os.path.join(game_dir, "valheim_Data", "StreamingAssets", "SoftRef", "Bundles", "*")))
    item_names, item_tokens, creature_tokens, drops = {}, {}, {}, {}
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

        fresh = []
        for tt in mbs:
            go = pp(tt.get("m_GameObject"))
            if not go:
                continue
            if "m_itemData" in tt:
                # a drop points at the item prefab's game object, which is the one holding its ItemDrop
                fresh.append(("item", go, tt["m_itemData"].get("m_shared", {}).get("m_name")))
            elif "m_killedForAchievements" in tt and "m_name" in tt:
                fresh.append(("creature", root_of(go), tt["m_name"]))
            elif "m_drops" in tt and "m_dropMin" not in tt and isinstance(tt["m_drops"], list) and \
                    tt["m_drops"] and isinstance(tt["m_drops"][0], dict) and "m_amountMin" in tt["m_drops"][0]:
                fresh.append(("drops", root_of(go), [(pp(d.get("m_prefab")), d.get("m_chance"), d.get("m_levelMultiplier"))
                                                     for d in tt["m_drops"]]))
        wanted = {go for _, go, _ in fresh if go}
        names = {}
        for o in env.objects:
            if o.type.name == "GameObject" and o.path_id in wanted:
                try:
                    names[o.path_id] = o.read_typetree().get("m_Name")
                except Exception:
                    pass
        for kind, go, value in fresh:
            name = names.get(go)
            if not name:
                continue
            if kind == "item":
                item_names[go] = name
                item_tokens.setdefault(name, value)
            elif kind == "creature":
                creature_tokens.setdefault(name, value)
            elif name not in drops:
                drops[name] = value
        if n % 100 == 0:
            log(f"  {n}/{len(bundles)} bundles, {int(time.time() - t0)} s")
    # the item references are game object ids; turn them into prefab names now that every bundle has been read
    resolved = {}
    for creature, entries in drops.items():
        rows = [(item_names[pid], chance, bool(scales)) for pid, chance, scales in entries
                if pid in item_names and chance is not None]
        if rows:
            resolved[creature] = rows
    return resolved, creature_tokens, item_tokens


def build(drops, creature_tokens, item_tokens, loc):
    def name(token, fallback):
        return loc.get((token or "").lstrip("$")) or fallback

    for prefab in list(drops) + [i for rows in drops.values() for i, _, _ in rows]:
        if "." in prefab:
            sys.exit(f"{prefab!r} has a dot in its name, which drop_counters.py uses to separate the parts of a filter")
    lines = [BEGIN + " (tools/update_drop_data.py rewrites everything up to END GENERATED DROPS)",
             "# Creature prefab -> (display name, [(item prefab, drop chance, stars raise the chance), ...]) from each",
             "# creature's CharacterDrop. Chances are the game's 32-bit floats, in the fewest digits that read back the same.",
             "DROPS = {"]
    for creature in sorted(drops):
        lines.append(f"    {creature!r}: ({name(creature_tokens.get(creature), creature)!r}, [")
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
    drops, creature_tokens, item_tokens = scan(args.game)
    block, item_count = build(drops, creature_tokens, item_tokens, read_localization(args.game))
    target = Path(__file__).resolve().parent.parent / "drop_counters.py"
    text = target.read_text()
    new = re.sub(re.escape(BEGIN) + r".*?" + re.escape(END), lambda m: block, text, flags=re.S)
    if new == text and block not in text:
        sys.exit("generated block markers not found in drop_counters.py")
    target.write_text(new)
    print(f"{len(drops)} creatures, {item_count} items")


if __name__ == "__main__":
    main()
