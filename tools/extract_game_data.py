#!/usr/bin/env python3
"""Read Valheim's own game files and write recipe and gatherable-item tables.

This is a developer tool. It is not needed to run achi_hunter.py. It needs UnityPy (pip install UnityPy) and a local
Valheim install, and takes about five minutes.

    python3 tools/extract_game_data.py --game "<path to steamapps/common/Valheim>" --out data

Outputs (in --out):
    recipes.csv / recipes.json        every crafting recipe and every build piece with its ingredients and station
    gatherables.csv / gatherables.json  every item that can be found in the world, with the earliest biome

Phase 1 scans the asset bundles once and keeps the raw facts in raw.json (so phase 2 can be re-run in seconds with
--raw raw.json). Phase 2 turns them into the tables.
"""
import argparse
import csv
import glob
import json
import os
import struct
import sys
import time
from collections import defaultdict
from pathlib import Path

# ---------------------------------------------------------------------------------------------------------------
# Phase 1: scan the bundles
# ---------------------------------------------------------------------------------------------------------------

def pp(x):
    """Path id of a PPtr dict ({m_FileID, m_PathID}); None for null."""
    if isinstance(x, dict):
        v = x.get("m_PathID")
        return v or None
    return None


def drop_table(t):
    """DropTable -> plain dict of the facts we need."""
    if not isinstance(t, dict):
        return None
    drops = [{"item": pp(d.get("m_item")), "min": d.get("m_stackMin"), "max": d.get("m_stackMax"),
              "weight": d.get("m_weight")} for d in t.get("m_drops", []) if isinstance(d, dict)]
    drops = [d for d in drops if d["item"]]
    if not drops:
        return None
    return {"drops": drops, "chance": t.get("m_dropChance", 1.0), "min": t.get("m_dropMin"), "max": t.get("m_dropMax")}


def transform_info(raw):
    """(game object path id, father transform path id) from a Transform's raw bytes (Unity 6 layout)."""
    go = struct.unpack_from("<q", raw, 4)[0]
    n = struct.unpack_from("<i", raw, 52)[0]
    father = struct.unpack_from("<q", raw, 56 + 12 * n + 4)[0]
    return go, father


def read_localization(game_dir):
    """English display names (token without the leading $ -> name) from the game's localization table."""
    import re
    data = (Path(game_dir) / "valheim_Data" / "resources.assets").read_bytes()
    names = {}
    for k, v in re.findall(rb'\n"([A-Za-z0-9_]+)","([^"\r\n]*)"', data):
        try:
            names.setdefault(k.decode(), v.decode("utf8"))
        except UnicodeDecodeError:
            pass
    return names


def scan(game_dir, log=print):
    bundles = sorted(glob.glob(os.path.join(game_dir, "valheim_Data", "StreamingAssets", "SoftRef", "Bundles", "*")))
    import UnityPy
    out = defaultdict(list)
    t0 = time.time()
    for n, path in enumerate(bundles):
        try:
            env = UnityPy.load(path)
        except Exception:
            continue
        mark = {k: len(v) for k, v in out.items()}
        father_of, transform_of = {}, {}   # transform -> father transform ; game object -> its transform
        tgo = {}
        mbs = []
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
                    tt = o.read_typetree()
                except Exception:
                    continue
                mbs.append((o.path_id, tt))

        def root_of(go):
            seen = 0
            tr = transform_of.get(go)
            while tr and seen < 64:
                f = father_of.get(tr)
                if not f:
                    return tgo.get(tr)
                tr, seen = f, seen + 1
            return go

        for pid, tt in mbs:
            go = pp(tt.get("m_GameObject"))
            root = root_of(go) if go else None
            base = {"pid": pid, "go": go, "root": root, "bundle": os.path.basename(path)}
            if "m_itemData" in tt:
                sh = tt["m_itemData"].get("m_shared", {})
                out["items"].append({**base, "token": sh.get("m_name"), "type": sh.get("m_itemType"),
                                     "food": sh.get("m_food"), "maxQuality": sh.get("m_maxQuality"),
                                     "stack": sh.get("m_maxStackSize"), "bp": pp(sh.get("m_buildPieces"))})
            elif isinstance(tt.get("m_conversion"), list) and tt["m_conversion"] and isinstance(tt["m_conversion"][0], dict):
                kind = ("cooking" if "m_cookTime" in tt["m_conversion"][0] else
                        "fermenting" if "m_producedItems" in tt["m_conversion"][0] else "smelting")
                out["conversions"].append({**base, "how": kind, "fuel": pp(tt.get("m_fuelItem")), "name": tt.get("m_name"),
                                           "list": [{"from": pp(c.get("m_from")), "to": pp(c.get("m_to")),
                                                     "time": c.get("m_cookTime"), "produced": c.get("m_producedItems")}
                                                    for c in tt["m_conversion"]]})
            elif "m_killedForAchievements" in tt and "m_name" in tt:
                out["characters"].append({**base, "token": tt["m_name"], "boss": tt.get("m_boss"),
                                          "achievement": tt.get("m_killedForAchievements")})
            elif "m_resources" in tt and "m_item" in tt and tt.get("m_Name", "").startswith("Recipe"):
                out["recipes"].append({**base, "name": tt["m_Name"], "item": pp(tt["m_item"]), "amount": tt.get("m_amount"),
                                       "enabled": tt.get("m_enabled"), "station": pp(tt.get("m_craftingStation")),
                                       "minLevel": tt.get("m_minStationLevel"), "onlyOne": tt.get("m_requireOnlyOneIngredient"),
                                       "resources": [{"item": pp(r.get("m_resItem")), "amount": r.get("m_amount"),
                                                      "perLevel": r.get("m_amountPerLevel"), "onlyOneExtra": r.get("m_extraAmountOnlyOneIngredient")}
                                                     for r in tt["m_resources"]]})
            elif "m_groundPiece" in tt and "m_name" in tt:
                out["pieces"].append({**base, "token": tt["m_name"], "enabled": tt.get("m_enabled"), "category": tt.get("m_category"),
                                      "station": pp(tt.get("m_craftingStation")), "repair": tt.get("m_repairPiece"),
                                      "resources": [{"item": pp(r.get("m_resItem")), "amount": r.get("m_amount")}
                                                    for r in tt.get("m_resources", [])]})
            elif "m_pieces" in tt and "m_canRemovePieces" in tt:
                out["piecetables"].append({**base, "can": tt["m_canRemovePieces"], "name": tt.get("m_Name"),
                                           "pieces": [pp(p) for p in tt["m_pieces"]]})
            elif "m_craftRequireFire" in tt and "m_name" in tt:
                out["stations"].append({**base, "token": tt["m_name"]})
            elif "m_extraDrops" in tt and "m_itemPrefab" in tt:
                out["pickables"].append({**base, "item": pp(tt["m_itemPrefab"]), "amount": tt.get("m_amount"),
                                         "extra": drop_table(tt.get("m_extraDrops"))})
            elif "m_dropWhenDestroyed" in tt and "m_logPrefab" in tt:
                out["trees"].append({**base, "log": pp(tt["m_logPrefab"]), "drops": drop_table(tt["m_dropWhenDestroyed"]),
                                     "tier": tt.get("m_minToolTier")})
            elif "m_dropWhenDestroyed" in tt and "m_subLogPrefab" in tt:
                out["logs"].append({**base, "sub": pp(tt["m_subLogPrefab"]), "drops": drop_table(tt["m_dropWhenDestroyed"])})
            elif "m_spawnWhenDestroyed" in tt:
                out["destructibles"].append({**base, "spawn": pp(tt["m_spawnWhenDestroyed"])})
            elif "m_dropItems" in tt and "m_minToolTier" in tt:
                out["rocks"].append({**base, "drops": drop_table(tt["m_dropItems"]), "tier": tt.get("m_minToolTier"),
                                     "name": tt.get("m_name")})
            elif "m_dropWhenDestroyed" in tt and "m_spawnYOffset" in tt:
                out["dropondestroyed"].append({**base, "drops": drop_table(tt["m_dropWhenDestroyed"])})
            elif "m_drops" in tt and "m_dropMin" not in tt and isinstance(tt["m_drops"], list) and \
                    tt["m_drops"] and isinstance(tt["m_drops"][0], dict) and "m_amountMin" in tt["m_drops"][0]:
                out["characterdrops"].append({**base, "drops": [{"item": pp(d.get("m_prefab")), "min": d.get("m_amountMin"),
                                                                "max": d.get("m_amountMax"), "chance": d.get("m_chance")}
                                                               for d in tt["m_drops"]]})
            elif "m_defaultItems" in tt and isinstance(tt["m_defaultItems"], dict):
                out["containers"].append({**base, "drops": drop_table(tt["m_defaultItems"])})
            elif "m_items" in tt and "m_dropMin" not in tt and isinstance(tt.get("m_items"), dict):
                out["lootspawners"].append({**base, "drops": drop_table(tt["m_items"])})
            elif "m_pickupItem" in tt and "m_extraDrops" in tt:
                out["fish"].append({**base, "item": pp(tt["m_pickupItem"]), "extra": drop_table(tt["m_extraDrops"])})
            elif "m_honeyItem" in tt:
                out["beehives"].append({**base, "item": pp(tt["m_honeyItem"]), "biome": tt.get("m_biome")})
            elif "m_spawners" in tt and isinstance(tt["m_spawners"], list):
                out["spawnlists"].append({**base, "spawners": [{"name": s.get("m_name"), "enabled": s.get("m_enabled"),
                                                               "devDisabled": s.get("m_devDisabled"), "prefab": pp(s.get("m_prefab")),
                                                               "biome": s.get("m_biome"), "area": s.get("m_biomeArea"),
                                                               "key": s.get("m_requiredGlobalKey"), "envs": s.get("m_requiredEnvironments"),
                                                               "event": s.get("m_requiredPersistentEvent")} for s in tt["m_spawners"]]})
            elif "m_vegetation" in tt and "m_locations" in tt:
                out["zonesystem"].append({**base,
                                          "vegetation": [{"name": v.get("m_name"), "prefab": pp(v.get("m_prefab")), "enable": v.get("m_enable"),
                                                          "biome": v.get("m_biome"), "area": v.get("m_biomeArea"), "min": v.get("m_min"),
                                                          "max": v.get("m_max")} for v in tt["m_vegetation"]],
                                          "locations": [{"name": l.get("m_name"), "prefabName": l.get("m_prefabName"), "enable": l.get("m_enable"),
                                                         "biome": l.get("m_biome"), "quantity": l.get("m_quantity"),
                                                         "unique": l.get("m_unique")} for l in tt["m_locations"]]})
            elif "m_theme" in tt and "m_endCap" in tt:
                out["rooms"].append({**base, "theme": tt["m_theme"], "enabled": tt.get("m_enabled")})
            elif "m_themes" in tt and "m_algorithm" in tt:
                out["dungeongens"].append({**base, "themes": tt["m_themes"]})
            elif isinstance(tt.get("m_items"), list) and tt["m_items"] and isinstance(tt["m_items"][0], dict) \
                    and "m_price" in tt["m_items"][0]:
                out["traders"].append({**base, "name": tt.get("m_name"),
                                       "items": [{"item": pp(i.get("m_prefab")), "price": i.get("m_price"),
                                                  "key": i.get("m_requiredGlobalKey")} for i in tt["m_items"]]})
            elif "m_grownPrefab" in tt and "m_growTime" in tt:
                out["eggs"].append({**base, "grown": pp(tt["m_grownPrefab"]), "growTime": tt.get("m_growTime")})
            elif "m_maxStationDistance" in tt and "m_craftingStation" in tt:
                out["extensions"].append({**base, "station": pp(tt["m_craftingStation"]), "stack": tt.get("m_stack")})
            elif "m_grownPrefabs" in tt:
                out["plants"].append({**base, "grown": [pp(g) for g in tt["m_grownPrefabs"]], "biome": tt.get("m_biome"),
                                      "cultivated": tt.get("m_needCultivatedGround")})
            elif "m_bossPrefab" in tt:
                out["bosssummons"].append({**base, "prefab": pp(tt["m_bossPrefab"])})
            elif "m_creaturePrefab" in tt:
                out["creaturespawners"].append({**base, "prefab": pp(tt["m_creaturePrefab"])})

        # names of the root game objects of everything kept from this bundle
        fresh = [r for k, lst in out.items() for r in lst[mark.get(k, 0):]]
        wanted = {r["root"] for r in fresh if r.get("root")} | {r["go"] for r in fresh if r.get("go")}
        names = {}
        for o in env.objects:
            if o.type.name == "GameObject" and o.path_id in wanted:
                try:
                    names[o.path_id] = o.read_typetree().get("m_Name")
                except Exception:
                    pass
        for r in fresh:
            r["rootName"] = names.get(r.get("root"))
            r["goName"] = names.get(r.get("go"))
        if n % 100 == 0:
            log(f"  {n}/{len(bundles)} bundles, {int(time.time() - t0)} s")
    out = dict(out)
    out["loc"] = read_localization(game_dir)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--game", help="path to the Valheim install (the folder containing valheim_Data)")
    ap.add_argument("--out", default="data", help="output folder (default: data)")
    ap.add_argument("--raw", help="reuse or write the raw scan here (default: <out>/raw.json)")
    ap.add_argument("--rescan", action="store_true", help="scan the game even if the raw file exists")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    raw_path = Path(args.raw) if args.raw else out / "raw.json"
    if raw_path.exists() and not args.rescan:
        raw = json.loads(raw_path.read_text())
    else:
        if not args.game:
            ap.error("--game is required for a scan")
        raw = scan(args.game)
        raw_path.write_text(json.dumps(raw))
    from derive import derive  # noqa: E402  (phase 2 lives in tools/derive.py)
    derive(raw, out)


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent))
    main()
