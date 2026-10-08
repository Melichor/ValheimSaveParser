"""Phase 2 of tools/extract_game_data.py: turn the raw scan into the recipe and gatherable-item tables."""
import csv
import json
from collections import defaultdict

ITEM_TYPES = {1: "Material", 2: "Consumable", 3: "OneHandedWeapon", 4: "Bow", 5: "Shield", 6: "Helmet", 7: "Chest",
              9: "Ammo", 10: "Customization", 11: "Legs", 12: "Hands", 13: "Trophy", 14: "TwoHandedWeapon",
              15: "Torch", 16: "Misc", 17: "Shoulder", 18: "Utility", 19: "Tool", 20: "Attach_Atgeir", 21: "Fish",
              22: "TwoHandedWeaponLeft", 23: "AmmoNonEquipable", 24: "Trinket"}
PIECE_CATEGORIES = {0: "Misc", 1: "Crafting", 2: "Building (workbench)", 3: "Building (stonecutter)", 4: "Furniture",
                    5: "Deep North", 6: "Feasts", 7: "Food", 8: "Meads"}

# Heightmap.Biome bit flags, in the order a player reaches them. A raft can technically leave Meadows, but the open
# Ocean is not viable without Bronze, so the Ocean is a step between the Black Forest and the Swamp.
BIOMES = [(1, "Meadows"), (8, "Black Forest"), (256, "Ocean"), (2, "Swamp"), (4, "Mountain"), (16, "Plains"),
          (512, "Mistlands"), (32, "Ashlands"), (64, "Deep North")]
OCEAN = 256
RANK = {name: i for i, (_, name) in enumerate(BIOMES, 1)}
BIOME_NAME = {bit: name for bit, name in BIOMES}


# Rules that cannot be read from the game files. Each one is a statement about the game, not something measured.
#
# Prefabs the world-generation data never places, but whose biome is known (prefab name -> Heightmap.Biome bit):
#   the Bog Witch's camp is in the Swamp; the "Hole" caves (generators DG_Hole and TheHole01) are entered through the
#   StumpHole prefabs that do appear in the Deep North vegetation list; Zil (Hildir's Plains fortress miniboss) is
#   spawned by code together with Thungr, so no spawner in the data mentions her; DN_Bossroom is the Frozen King's
#   arena, which is not in any location list; the Jotun Witch (Hexen), Jotun Warriors (Krigen) and Frost Blobs only
#   spawn in Deep North but are placed by the Fimbulvinter event or by code.
MANUAL_PLACEMENT = {"BogWitch_Camp": 2, "DG_Hole": 64, "TheHole01": 64, "GoblinShaman_Hildir": 16, "DN_Bossroom": 64,
                    "JotunWitch": 64, "JotunWarrior": 64, "JotunWarriorDualWield": 64, "BlobFrost": 64,
                    "BlobMork": 64, "BlobMorkBig": 64, "BlobMorkMini": 64}
# Items that only appear when a player builds a structure, and which structure (item -> piece):
#   Wisp comes from the Wisplight structure (Yagluth's Torn Spirit), Embers from the Fader ember structure, Sap from the
#   sap extractor. The number is a biome the structure must stand in (0 = anywhere).
ITEM_FROM_STRUCTURE = {"$item_wisp": ("$piece_wisplure", 0), "$item_faderember": ("$piece_faderember", 0),
                       "$item_sap": ("$piece_sapcollector", 512)}   # the sap extractor is placed on a Yggdrasil root (Mistlands)
# Items whose world source the data does not place (item -> (Heightmap.Biome bit, how it is found, label)):
#   Fenris Claw drops in Mountain dungeons; Sealbreaker fragments are treated as available in Mistlands;
#   Petrified Tissue (the "goldore" item, smelted into Bloodgold) is mined from the corpse of a Gammeltroll in Deep North.
MANUAL_ITEM_BIOME = {"$item_wolfclaw": (4, "loot", "dungeons (assumed)"),
                     "$item_dvergrkeyfragment": (512, "loot", "dungeons (assumed)"),
                     "$item_goldore": (64, "mining", "Gammeltroll corpse"),
                     # Ancient Coin and the four ancient gemstones (Draumyx, Grimvarn, Solryth, Veydris) come from the
                     # same Mork Halla chests
                     "$item_ancientcoin": (64, "loot", "Deep North dungeons"),
                     "$item_ancientgemstone_black": (64, "loot", "Deep North dungeons (assumed)"),
                     "$item_ancientgemstone_green": (64, "loot", "Deep North dungeons (assumed)"),
                     "$item_ancientgemstone_orange": (64, "loot", "Deep North dungeons (assumed)"),
                     "$item_ancientgemstone_purple": (64, "loot", "Deep North dungeons (assumed)"),
                     # Frostfire and Thunderblood Essence come from sacrificing Memorial Coal (a Deep North item)
                     "$item_orbfrostfire": (64, "offering", "sacrificing Memorial Coal"),
                     "$item_orbthunderblood": (64, "offering", "sacrificing Memorial Coal"),
                     # oats and poteitr grow in the North villages; the Frozen King is Deep North's last boss
                     "$item_oatseeds": (64, "pickable", "North village"),
                     "$item_poteitrseeds": (64, "pickable", "North village"),
                     "$item_crownjewel": (64, "boss", "Frozen King"),
                     "$item_frozenking_drop": (64, "boss", "Frozen King"),
                     # dropped by destroying a Standing Lantern, a very rare structure, found in Meadows at the earliest
                     "$item_lanternDN": (1, "destructible", "Standing Lantern (very rare)")}
# Every mould is a Deep North item (dungeons and mobs).
MANUAL_ITEM_PREFIX = {"$item_mold": (64, "loot", "Deep North dungeons and mobs")}
# Creatures the data does not place (nested prefabs, summons, offspring): token -> biome bit, or another creature's token
# whose biome they share. Young animals follow their parents; the "aspects" and the Fallen Warrior are Deep North.
# Left without a biome: the training dummy and creatures a player summons (Skeleton_Friendly, Troll_Summoned, the
# Spirit Caller animals).
CREATURE_BIOME_RULES = {
    "$enemy_asksvin_hatchling": "$enemy_asksvin", "$enemy_boarpiggy": "$enemy_boar", "$enemy_loxcalf": "$enemy_lox",
    "$enemy_moosecalf": "$enemy_moose", "$enemy_wolfcub": "$enemy_wolf", "$enemy_babyseeker": "$enemy_seeker",
    "$enemy_charred_twitcher_summoned": "$enemy_charred_twitcher", "$enemy_charred_melee_Fader": "$enemy_charred_melee",
    "$enemy_chicken": 1, "$enemy_hen": 1,                 # the farm spawners of the Meadows
    "$enemy_kvastur": 2,                                   # the Bog Witch's familiar (Swamp)
    "$enemy_root": 512,                                    # Yggdrasil roots (Mistlands)
    "$enemy_dvergr_deepnorth": 64, "$enemy_goblin_deepnorth": 64, "$enemy_fallenwarrior": 64,
    "$enemy_aspect_bonemass": 64, "$enemy_aspect_dragon": 64, "$enemy_aspect_eikthyr": 64, "$enemy_aspect_fader": 64,
    "$enemy_aspect_gdking": 64, "$enemy_aspect_goblinking": 64, "$enemy_aspect_seekerqueen": 64,
}
# A trader item that needs a defeated boss is only as early as that boss's biome (key -> Heightmap.Biome bit).
KEY_BIOME = {"defeated_eikthyr": 1, "defeated_gdking": 8, "defeated_bonemass": 2, "defeated_dragon": 4,
             "defeated_goblinking": 16, "defeated_queen": 512, "defeated_fader": 32, "defeated_frozenking_p3": 64,
             "defeated_writhan": 2, "Hildir1": 8, "Hildir2": 4, "Hildir3": 16}   # Hildir1-3: Brenna, Geirrhafa, Zil & Thungr


def biome_names(mask):
    return [name for bit, name in BIOMES if mask & bit]


def derive(raw, out):
    loc = raw["loc"]

    def name_of(token):
        k = (token or "").lstrip("$")
        v = loc.get(k)
        if not v:
            low = {x.lower(): y for x, y in loc.items()} if not hasattr(name_of, "low") else name_of.low
            name_of.low = low
            v = low.get(k.lower())
        return (v or k).replace("<color=orange>", "").replace("</color>", "").strip()

    items = raw["items"]
    item_by_pid = {i["pid"]: i for i in items}
    item_by_go = {i["go"]: i for i in items if i["go"]}
    station_by_pid = {s["pid"]: s["token"] for s in raw["stations"]}

    # ---------------------------------------------------------------- recipes
    recipe_rows, piece_rows = [], []
    for r in raw["recipes"]:
        item = item_by_pid.get(r["item"])
        if not item:
            continue
        ing = []
        for x in r["resources"]:
            it = item_by_pid.get(x["item"])
            if it and "upgrader" not in it["token"]:   # marker entries, not real materials
                # the per-level amount only matters for equipment that can be upgraded
                per_level = x["perLevel"] if (item["maxQuality"] or 1) > 1 else 0
                ing.append({"token": it["token"], "name": name_of(it["token"]), "amount": x["amount"], "per_level": per_level})
        station = station_by_pid.get(r["station"], "")
        recipe_rows.append({
            "kind": "item", "output": item["token"], "output_name": name_of(item["token"]),
            "item_type": ITEM_TYPES.get(item["type"], item["type"]), "output_amount": r["amount"],
            "station": station, "station_name": name_of(station) if station else "(hand / no station)",
            "min_station_level": r["minLevel"] if station else "", "max_quality": item["maxQuality"],
            "any_one_ingredient": bool(r["onlyOne"]), "enabled": bool(r["enabled"]), "recipe_asset": r["name"],
            "ingredients": ing,
        })

    tables = {t["go"]: (t.get("goName") or t.get("name") or "table") for t in raw["piecetables"]}
    piece_by_go = {p["go"]: p for p in raw["pieces"] if p["go"] == p.get("root")}
    seen = set()
    for t in raw["piecetables"]:
        table = (t.get("goName") or t.get("name") or "").strip("_").replace("PieceTable", "")
        for go in t["pieces"]:
            p = piece_by_go.get(go)
            if not p or (p["token"], table) in seen:
                continue
            seen.add((p["token"], table))
            ing = []
            for x in p["resources"]:
                it = item_by_pid.get(x["item"])
                if it:
                    ing.append({"token": it["token"], "name": name_of(it["token"]), "amount": x["amount"], "per_level": 0})
            station = station_by_pid.get(p["station"], "")
            piece_rows.append({
                "kind": "piece", "output": p["token"], "output_name": name_of(p["token"]), "item_type": "Piece",
                "category": PIECE_CATEGORIES.get(p["category"], p["category"]), "build_table": table,
                "output_amount": 1, "station": station, "station_name": name_of(station) if station else "(none)",
                "min_station_level": "", "enabled": bool(p["enabled"]), "recipe_asset": p.get("goName"),
                "ingredients": ing,
            })

    piece_token_by_root = {}
    for p in raw["pieces"]:
        if p["go"] == p.get("root"):
            piece_token_by_root.setdefault(p["root"], p["token"])
    seen_conv = set()
    for c in raw["conversions"]:
        station = piece_token_by_root.get(c["root"]) or c.get("name") or ""
        fuel = item_by_pid.get(c["fuel"])
        for x in c["list"]:
            src, dst = item_by_pid.get(x["from"]), item_by_pid.get(x["to"])
            if not src or not dst or (station, src["token"], dst["token"]) in seen_conv:
                continue
            seen_conv.add((station, src["token"], dst["token"]))
            recipe_rows.append({
                "kind": c["how"], "output": dst["token"], "output_name": name_of(dst["token"]),
                "item_type": ITEM_TYPES.get(dst["type"], dst["type"]), "output_amount": x.get("produced") or 1,
                "station": station, "station_name": name_of(station) if station else c.get("name") or "",
                "min_station_level": "", "max_quality": "", "any_one_ingredient": False, "enabled": True,
                "recipe_asset": c.get("rootName"), "fuel": name_of(fuel["token"]) if fuel else "",
                "ingredients": [{"token": src["token"], "name": name_of(src["token"]), "amount": 1, "per_level": 0}],
            })

    # --------------------------------------------------------------- gatherables
    by_root = defaultdict(list)
    for kind in ("pickables", "trees", "logs", "rocks", "destructibles", "dropondestroyed", "characterdrops",
                 "containers", "lootspawners", "fish", "creaturespawners", "bosssummons", "traders"):
        for rec in raw.get(kind, []):
            if rec.get("root"):
                by_root[rec["root"]].append((kind, rec))

    for it in items:   # item instances placed inside a location or room (ItemDrop that is not the prefab root)
        if it.get("root") and it["root"] != it["go"] and it["token"]:
            by_root[it["root"]].append(("placed", it))

    def table_items(t):
        return [d["item"] for d in t["drops"]] if t else []

    def yields(root, kind_hint=None, depth=0, seen=None):
        """Items that a prefab (and everything inside it) can give, as {(token, source kind)}."""
        seen = seen if seen is not None else set()
        if root in seen or depth > 8:
            return set()
        seen.add(root)
        out = set()

        def add(go, kind):
            it = item_by_go.get(go)
            if it and it["token"]:
                out.add((it["token"], kind_hint or kind))

        for kind, rec in by_root.get(root, []):
            if kind == "pickables":
                add(rec["item"], "pickable")
                for g in table_items(rec["extra"]):
                    add(g, "pickable")
            elif kind == "trees":
                for g in table_items(rec["drops"]):
                    add(g, "tree")
                out |= yields(rec["log"], kind_hint or "tree", depth + 1, seen)
            elif kind == "logs":
                for g in table_items(rec["drops"]):
                    add(g, "tree")
                out |= yields(rec["sub"], kind_hint or "tree", depth + 1, seen)
            elif kind == "rocks":
                for g in table_items(rec["drops"]):
                    add(g, "mining")
            elif kind == "destructibles":
                out |= yields(rec["spawn"], kind_hint, depth + 1, seen)
            elif kind == "dropondestroyed":
                for g in table_items(rec["drops"]):
                    add(g, "destructible")
            elif kind == "characterdrops":
                for d in rec["drops"]:
                    add(d["item"], "creature")
            elif kind in ("containers", "lootspawners"):
                for g in table_items(rec["drops"]):
                    add(g, "loot")
            elif kind == "placed":
                if rec["type"] != 21:
                    out.add((rec["token"], kind_hint or "loot"))
            elif kind == "fish":
                add(rec["go"], "fishing")   # the fish is itself an item
                add(rec["item"], "fishing")
                for g in table_items(rec["extra"]):
                    add(g, "fishing bonus")   # extra items some fish carry (ore, seeds, ...)
            elif kind == "creaturespawners":
                out |= yields(rec["prefab"], "creature", depth + 1, seen)
            elif kind == "bosssummons":
                out |= yields(rec["prefab"], "boss", depth + 1, seen)
            elif kind == "traders":
                for t in rec["items"]:
                    it = item_by_pid.get(t["item"])
                    if it and it["token"]:
                        out.add((it["token"], "trader:" + (t["key"] or "")))
        return out

    # where each prefab shows up and in which biomes
    root_by_name = {}
    for kind in ("pickables", "trees", "rocks", "containers", "dungeongens", "creaturespawners", "destructibles", "bosssummons", "traders", "characters"):
        for rec in raw.get(kind, []):
            if rec.get("rootName") and rec.get("root"):
                root_by_name.setdefault(rec["rootName"], rec["root"])
    rooms = raw["rooms"]
    gens = {g["root"]: g["themes"] for g in raw["dungeongens"] if g.get("root")}

    sources = []   # (root, biome mask, where, label)
    seen_src = set()

    def add_source(root, mask, where, label):
        key = (root, mask, where)
        if root and mask and key not in seen_src:
            seen_src.add(key)
            sources.append((root, mask, where, label))

    for z in raw["zonesystem"]:
        for v in z["vegetation"]:
            if v["enable"] and (v["max"] or 0) > 0:
                add_source(v["prefab"], v["biome"], "world", v["name"])
        for l in z["locations"]:
            if l["enable"]:
                root = root_by_name.get(l["prefabName"])
                add_source(root, l["biome"], "location", l["prefabName"])
    # Prefabs the game data never places in the world but that are known to exist in one biome (the Bog Witch's camp
    # is not in any location list in this version; she is found in the Swamp).
    for name, bit in MANUAL_PLACEMENT.items():
        add_source(root_by_name.get(name), bit, "location (assumed)", name)
    for sl in raw["spawnlists"]:
        for s in sl["spawners"]:
            if s["enabled"] and not s["devDisabled"] and not s["key"] and not s["event"]:
                # skip spawns that need a defeated boss or a world event (Fimbulvinter)
                add_source(s["prefab"], s["biome"], "creature", s["name"])

    found = defaultdict(lambda: {"biomes": defaultdict(set), "labels": defaultdict(set)})
    bought = defaultdict(lambda: {"biomes": defaultdict(set), "labels": defaultdict(set)})   # sold by traders
    for root, mask, where, label in sources:
        got = yields(root)
        themes = gens.get(root)
        if themes:   # dungeons: rooms are placed from the generator's themes
            for room in rooms:
                if room["enabled"] and room["theme"] & themes and room["root"]:
                    got |= {(t, "loot" if k == "loot" else k) for t, k in yields(room["root"])}
        for token, kind in got:
            m = mask
            if kind.startswith("trader"):
                key = kind.partition(":")[2]
                kind = "trader"
                kb = KEY_BIOME.get(key)
                lands = [b for b, _ in BIOMES]
                if kb and mask & sum(lands) and lands.index(kb) > min(lands.index(b) for b in lands if mask & b):
                    m = kb   # the trader's goods need a boss from a later biome
            f = (bought if kind == "trader" else found)[token]
            for bit in [b for b, _ in BIOMES]:
                if m & bit:
                    f["biomes"][kind].add(bit)
            f["labels"][kind].add(label)
    manual = dict(MANUAL_ITEM_BIOME)
    for prefix, rule in MANUAL_ITEM_PREFIX.items():
        manual.update({i["token"]: rule for i in items if i["token"] and i["token"].startswith(prefix)})
    char_by_root = {c["root"]: c for c in raw["characters"] if c.get("root") and c["root"] == c["go"]}
    creature_bits = defaultdict(set)

    def creatures_of(root, seen=None, depth=0):
        """Character tokens that a prefab is, or spawns (through spawners and boss altars)."""
        seen = seen if seen is not None else set()
        if root in seen or depth > 6:
            return set()
        seen.add(root)
        out = {char_by_root[root]["token"]} if root in char_by_root else set()
        for kind, rec in by_root.get(root, []):
            if kind in ("creaturespawners", "bosssummons") and rec.get("prefab"):
                out |= creatures_of(rec["prefab"], seen, depth + 1)
        return out

    for root, mask, where, label in sources:
        names = creatures_of(root)
        themes = gens.get(root)
        if themes:
            for room in rooms:
                if room["enabled"] and room["theme"] & themes and room["root"]:
                    names |= creatures_of(room["root"])
        for tok in names:
            creature_bits[tok] |= {b for b, _ in BIOMES if mask & b}
    for token, (bit, how, why) in manual.items():
        found[token]["biomes"][how].add(bit)
        found[token]["labels"][how].add(why)

    # Deep North is not fully wired into world generation in this game version: some of its prefabs (gold veins,
    # Frostfire essence, moulds, ...) exist but no location or spawner places them. For items that have no source
    # at all and whose only producers are Deep North prefabs, assume Deep North. These are kept apart as "inferred".
    import re
    deep_north = re.compile(r"^DN_|deepnorth|morkhalla|mork|frozen|frost|elaking|jotun|fallenwarrior|memorial|gammel|northern|nord",
                            re.I)
    producers = defaultdict(set)   # item token -> names of prefabs that can drop it
    for kind in ("pickables", "trees", "logs", "rocks", "dropondestroyed", "characterdrops", "containers", "lootspawners",
                 "fish"):
        for rec in raw.get(kind, []):
            if kind == "pickables":
                gos = [rec["item"]] + table_items(rec["extra"])
            elif kind == "characterdrops":
                gos = [d["item"] for d in rec["drops"]]
            elif kind == "fish":
                gos = [rec["go"], rec["item"]] + table_items(rec["extra"])
            else:
                gos = table_items(rec["drops"])
            for g in gos:
                it = item_by_go.get(g)
                if it and it["token"] and rec.get("rootName"):
                    producers[it["token"]].add(rec["rootName"])
    for it in items:
        if it.get("root") and it["root"] != it["go"] and it["token"] and it.get("rootName"):
            producers[it["token"]].add(it["rootName"])
    inferred = {t for t, names in producers.items()
                if t not in found and any(deep_north.search(n) for n in names if not n.startswith("Dev"))}

    # ------------------------------------------- how far into the game each biome is
    # A rank is the position in BIOMES. max() of ranks = "needs both"; min() = "either".
    land_rank = {bit: i for i, (bit, _) in enumerate(BIOMES, 1)}
    biome_by_rank = {i: n for i, (_, n) in enumerate(BIOMES, 1)}

    def label(rank):
        return "" if rank is None else biome_by_rank[rank]

    def mask_rank(bits):
        cand = [land_rank[b] for b in bits if b in land_rank]
        return min(cand) if cand else None

    def earliest(bits):
        r = mask_rank(bits)
        return r, label(r)

    # farming: planting a seed (a Cultivator piece) grows a pickable crop
    sapling_token = {}
    for p in raw["pieces"]:
        if p["go"] == p.get("root"):
            sapling_token.setdefault(p["root"], p["token"])
    farm_rows = []
    for pl in raw["plants"]:
        sap = sapling_token.get(pl["root"])
        crops = set()
        for g in pl["grown"]:
            crops |= {t for t, k in yields(g) if k == "pickable"}
        grow_bits = {b for b, _ in BIOMES if (pl["biome"] or 0) & b}
        for row in piece_rows:
            if row["output"] == sap:
                for crop in crops:
                    farm_rows.append({"kind": "farming", "output": crop, "output_name": name_of(crop),
                                      "item_type": "Crop", "output_amount": 1, "ingredients": row["ingredients"],
                                      "station": "", "station_name": "Cultivator + planting " + name_of(sap),
                                      "min_station_level": "", "max_quality": "", "any_one_ingredient": False,
                                      "enabled": row["enabled"], "recipe_asset": sap, "grow_bits": grow_bits,
                                      "needs": ["$item_cultivator"], "via": sap,
                                      "fuel": "grows in: " + ", ".join(biome_names(sum(grow_bits))) if grow_bits else ""})

    # items that exist only because a structure was built (Wisp, Embers)
    piece_name = {r["output"]: r["output_name"] for r in piece_rows}
    for item_token, (piece, bit) in ITEM_FROM_STRUCTURE.items():
        farm_rows.append({"kind": "structure", "output": item_token, "output_name": name_of(item_token), "item_type": "Material",
                          "output_amount": 1, "ingredients": [], "station": "", "min_station_level": "", "max_quality": "",
                          "station_name": "Built structure: " + piece_name.get(piece, piece), "any_one_ingredient": False,
                          "enabled": True, "recipe_asset": piece, "needs": [piece], "fuel": "",
                          "grow_bits": {bit} if bit else None})
    # eggs: hatching one gives a creature, whose drops become available
    for e in raw["eggs"]:
        egg = item_by_go.get(e["root"])
        if not egg or not e["grown"]:
            continue
        for token, kind in yields(e["grown"]):
            if kind == "creature":
                farm_rows.append({"kind": "hatching", "output": token, "output_name": name_of(token), "item_type": "Material",
                                  "output_amount": 1, "ingredients": [{"token": egg["token"], "name": name_of(egg["token"]),
                                                                        "amount": 1, "per_level": 0}],
                                  "station": "", "station_name": "Hatch " + name_of(egg["token"]), "min_station_level": "",
                                  "max_quality": "", "any_one_ingredient": False, "enabled": True,
                                  "recipe_asset": egg["rootName"], "fuel": ""})

    # station upgrades: a station of level L has L-1 extensions; an extension type counts once unless it stacks
    extension_token = {}
    for e in raw["extensions"]:
        tok = piece_token_by_root.get(e["root"])
        st = station_by_pid.get(e["station"])
        if tok and st:
            extension_token.setdefault(st, {})[tok] = bool(e["stack"])

    def compute(kinds):
        rank = {}
        for token, f in found.items():
            bits = set()
            for k, v in f["biomes"].items():
                if k in kinds:
                    bits |= v
            r = mask_rank(bits)
            if r is not None:
                rank[token] = r
        if "trader" in kinds:
            for token, f in bought.items():
                bits = set().union(*f["biomes"].values())
                r = mask_rank(bits)
                if r is not None and (token not in rank or r < rank[token]):
                    rank[token] = r
        if "inferred" in kinds:
            for token in inferred:
                rank[token] = mask_rank({64})

        def station_rank(st, level):
            base = rank.get(st)
            if base is None:
                return None
            if not level or level <= 1:
                return base
            exts = extension_token.get(st, {})
            avail = sorted((rank[t], s) for t, s in exts.items() if t in rank)
            need, got, stack_from = level - 1, 0, None
            for r, stacks in avail:
                if stacks:
                    stack_from = r if stack_from is None else min(stack_from, r)
            # smallest rank at which enough extensions exist
            for r, _ in avail:
                have = sum(1 for r2, s2 in avail if r2 <= r and not s2)
                if (stack_from is not None and stack_from <= r) or have >= need:
                    return max(base, r)
            return None

        def row_rank(row):
            if not row["enabled"] and row["kind"] != "piece":   # switched-off pieces (Yule, ...) still count as pieces
                return None
            ing = [rank.get(i["token"]) for i in row["ingredients"]]
            if row["ingredients"]:
                if row.get("any_one_ingredient"):
                    ing = [min(x for x in ing if x is not None)] if any(x is not None for x in ing) else [None]
                if any(x is None for x in ing):
                    return None
            parts = list(ing)
            if row["station"]:
                sr = station_rank(row["station"], row.get("min_station_level") or 1)
                if sr is None:
                    return None
                parts.append(sr)
            for t in row.get("needs", []):
                if t not in rank:
                    return None
                parts.append(rank[t])
            if row.get("grow_bits") is not None:
                gr = mask_rank(row["grow_bits"])
                if gr is None:
                    return None
                parts.append(gr)
            return max(parts) if parts else 1

        changed = True
        while changed:
            changed = False
            for row in recipe_rows + piece_rows + farm_rows:
                r = row_rank(row)
                if r is not None and (row["output"] not in rank or r < rank[row["output"]]):
                    rank[row["output"]] = r
                    changed = True
        return rank, row_rank

    # "fishing bonus" (ore, seeds, ... carried by some fish) is listed for information but never decides a biome
    STRICT_KINDS = {"pickable", "tree", "mining", "destructible", "creature", "fishing", "loot", "boss",
                    "trader", "offering"}
    ALL_KINDS = STRICT_KINDS
    DIRECT_KINDS = ALL_KINDS - {"loot", "boss", "offering"}   # traders stay: buying is not luck
    ranks, rank_row = compute(ALL_KINDS)
    # only assume Deep North for items that have no route at all (not found, not craftable, not bought)
    inferred = {t for t in inferred if t not in ranks and "upgrader" not in t}
    ranks_inf, rank_row_inf = compute(ALL_KINDS | {"inferred"})
    ranks_direct, rank_row_direct = compute(DIRECT_KINDS)
    for row in recipe_rows + piece_rows + farm_rows:
        row["biome_needed"] = label(rank_row(row))
        row["biome_needed_inferred"] = label(rank_row_inf(row)) if rank_row(row) is None else ""
        row["biome_needed_direct"] = label(rank_row_direct(row))

    # best recipe for every craftable thing, and what holds it back
    def limiting(row, rk):
        """Names of the ingredient(s) or station that set the biome of this recipe."""
        parts = [(rk.get(i["token"]), i["name"]) for i in row["ingredients"]]
        if row["station"] and rk.get(row["station"]) is not None:
            sr = rk[row["station"]]
            parts.append((sr, name_of(row["station"])))
        parts = [p for p in parts if p[0] is not None]
        if not parts:
            return []
        top = max(p[0] for p in parts)
        return sorted({n for r, n in parts if r == top})

    def blockers(row, rk):
        out = [i["name"] for i in row["ingredients"] if rk.get(i["token"]) is None]
        if row["station"] and rk.get(row["station"]) is None:
            out.append(name_of(row["station"]))
        return out

    craft_rows = []
    by_output = defaultdict(list)
    for row in recipe_rows + piece_rows + farm_rows:
        # hatching and structure rows only exist to link items to their source; they are not things you craft
        if (row["enabled"] or row["kind"] == "piece") and row["kind"] not in ("hatching", "structure"):
            by_output[(row["kind"] == "piece", row["output"])].append(row)   # a piece and an item can share a token
    for (is_piece, token), rows in by_output.items():
        def best(rank_fn):
            scored = [(rank_fn(r), i) for i, r in enumerate(rows)]
            ok = [x for x in scored if x[0] is not None]
            return (min(ok), rows[min(ok)[1]]) if ok else (None, rows[0])
        (r_any, row_any) = (lambda t: (t[0][0] if t[0] else None, t[1]))(best(rank_row))
        (r_dir, row_dir) = (lambda t: (t[0][0] if t[0] else None, t[1]))(best(rank_row_direct))
        (r_inf, row_inf) = (lambda t: (t[0][0] if t[0] else None, t[1]))(best(rank_row_inf))
        shown = row_any if r_any is not None else rows[0]
        craft_rows.append({
            "item": token, "name": name_of(token), "kind": shown["kind"],
            "type_or_category": shown.get("category") or shown.get("item_type", ""),
            "earliest_biome": label(r_any), "earliest_biome_direct": label(r_dir),
            "earliest_biome_inferred": label(r_inf) if r_any is None else "",
            "inferred_from": ([i["name"] for i in row_inf["ingredients"] if i["token"] in inferred] if r_any is None and r_inf is not None else []),
            "limited_by": limiting(row_any, ranks) if r_any is not None else [],
            "limited_by_direct": limiting(row_dir, ranks_direct) if r_dir is not None else [],
            "blocked_by": [] if r_any is not None else blockers(shown, ranks),
            "still_blocked_by": blockers(row_inf, ranks_inf) if r_any is None and r_inf is None else [],
            "station": shown.get("station_name", ""), "station_level": shown.get("min_station_level", ""),
            "ingredients": shown["ingredients"], "other_recipes": len(rows) - 1,
        })
    craft_rows.sort(key=lambda r: (RANK.get(r["earliest_biome"], 99), r["kind"], r["name"]))

    gather_rows = []
    item_by_token = {}
    for i in items:
        item_by_token.setdefault(i["token"], i)
    for token, f in found.items():
        item = item_by_token.get(token)
        by_kind = {kind: earliest(bits)[1] for kind, bits in f["biomes"].items()}
        main = [b for k, b in f["biomes"].items() if k != "fishing bonus"]
        all_bits = set().union(*main)   # fish bonus items never decide the biome
        no_loot = [b for k, b in f["biomes"].items() if k not in ("loot", "fishing bonus", "boss", "offering")]
        gather_rows.append({
            "item": token, "name": name_of(token), "item_type": ITEM_TYPES.get(item["type"], item["type"]) if item else "",
            "earliest_biome": earliest(all_bits)[1],
            "earliest_biome_direct": earliest(set().union(*no_loot))[1] if no_loot else "",
            "biomes": biome_names(sum(all_bits)),
            "sources": sorted(f["biomes"]),
            "earliest_by_source": by_kind,
            "examples": sorted({l for k, ls in f["labels"].items() for l in ls})[:6],
        })
    gather_rows.sort(key=lambda r: (RANK.get(r["earliest_biome"], 99), r["item_type"], r["name"]))

    # ------------------------------------------------------------------- write
    recipes = recipe_rows + piece_rows + farm_rows
    (out / "recipes.json").write_text(json.dumps([{k: v for k, v in r.items() if k != "grow_bits"} for r in recipes],
                                                 indent=1, ensure_ascii=False), encoding="utf-8")
    (out / "gatherables.json").write_text(json.dumps(
        {"biome_order": [n for _, n in BIOMES], "items": gather_rows}, indent=1, ensure_ascii=False), encoding="utf-8")

    def ing_text(r):
        out = []
        for i in r["ingredients"]:
            s = f"{i['name']} x{i['amount']}"
            if i.get("per_level"):
                s += f" (+{i['per_level']}/upgrade level)"
            out.append(s)
        return "; ".join(out)

    with open(out / "recipes.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["name", "kind", "type_or_category", "output_amount", "station", "min_station_level",
                    "ingredients", "any_one_ingredient", "max_quality", "biome_needed", "biome_needed_direct", "biome_needed_inferred", "notes", "enabled",
                    "recipe_asset", "token"])
        for r in recipes:
            w.writerow([r["output_name"], r["kind"], r.get("category") or r["item_type"], r["output_amount"],
                        r["station_name"], r["min_station_level"], ing_text(r), r.get("any_one_ingredient", ""),
                        r.get("max_quality", ""), r["biome_needed"], r["biome_needed_direct"], r["biome_needed_inferred"],
                        r["fuel"] if r["kind"] == "farming" else (("Fuel: " + r["fuel"]) if r.get("fuel") else ""),
                        r["enabled"], r["recipe_asset"], r["output"]])
    with open(out / "gatherables.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["name", "item_type", "earliest_biome", "earliest_biome_direct", "all_biomes", "found_via",
                    "earliest_by_source", "example_sources", "token"])
        for r in gather_rows:
            w.writerow([r["name"], r["item_type"], r["earliest_biome"], r["earliest_biome_direct"],
                        "; ".join(r["biomes"]), "; ".join(r["sources"]),
                        "; ".join(f"{k}: {v}" for k, v in sorted(r["earliest_by_source"].items())),
                        "; ".join(r["examples"]), r["item"]])
    (out / "craftable_biomes.json").write_text(json.dumps(
        {"biome_order": [n for _, n in BIOMES], "items": craft_rows}, indent=1, ensure_ascii=False), encoding="utf-8")
    with open(out / "craftable_biomes.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["name", "kind", "type_or_category", "earliest_biome", "limited_by", "earliest_biome_direct",
                    "limited_by_direct", "blocked_by", "earliest_biome_inferred", "inferred_from", "still_blocked_by", "station", "min_station_level", "ingredients", "other_recipes", "token"])
        for r in craft_rows:
            w.writerow([r["name"], r["kind"], r["type_or_category"], r["earliest_biome"], "; ".join(r["limited_by"]),
                        r["earliest_biome_direct"], "; ".join(r["limited_by_direct"]), "; ".join(r["blocked_by"]),
                        r["earliest_biome_inferred"], "; ".join(r["inferred_from"]), "; ".join(r["still_blocked_by"]),
                        r["station"], r["station_level"], ing_text(r), r["other_recipes"], r["item"]])

    # earliest biome per token, for achi_hunter.py (tools/update_script_biomes.py writes it into the script)
    def creature_biome(tok, depth=0):
        for t in (tok, tok.rsplit("_p", 1)[0] if "_p" in tok[-4:] else tok):   # boss phases share their boss's biome
            bits = creature_bits.get(t)
            if bits:
                return earliest(bits)[1]
        rule = CREATURE_BIOME_RULES.get(tok)
        if isinstance(rule, int):
            return earliest({rule})[1]
        if isinstance(rule, str) and depth < 3:
            return creature_biome(rule, depth + 1)
        return ""
    biomes_out = {
        "order": [n for _, n in BIOMES],
        "craft": {r["item"]: r["earliest_biome"] for r in craft_rows if r["kind"] != "piece" and r["earliest_biome"]},
        "piece": {r["item"]: r["earliest_biome"] for r in craft_rows if r["kind"] == "piece" and r["earliest_biome"]},
        "found": {r["item"]: r["earliest_biome"] for r in gather_rows if r["earliest_biome"]},
        "creature": {t: creature_biome(t) for t in {c["token"] for c in raw["characters"] if c.get("token")}
                     if creature_biome(t)},
    }
    (out / "biomes.json").write_text(json.dumps(biomes_out, indent=1, ensure_ascii=False), encoding="utf-8")

    # the items whose Deep North source is assumed (see the note above `inferred`), and what depends on them
    used_by = defaultdict(set)
    for r in craft_rows:
        for name in r["inferred_from"]:
            used_by[name].add(r["name"])
    with open(out / "inferred_items.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["name", "token", "assumed_biome", "producers", "craftable_items_that_depend_on_it"])
        for t in sorted(inferred, key=name_of):
            w.writerow([name_of(t), t, "Deep North", "; ".join(sorted(producers[t])[:5]),
                        "; ".join(sorted(used_by.get(name_of(t), []))[:8]) + (" ..." if len(used_by.get(name_of(t), [])) > 8 else "")])

    # materials, food, trophies and fish that are neither craftable nor found by the rules above
    made = {r["output"] for r in recipes}
    unsourced = sorted({i["token"] for i in items if i["token"] and i["type"] in (1, 2, 13, 21) and i["go"] == i["root"]
                        and i["token"] not in found and i["token"] not in made})
    with open(out / "unsourced_items.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["name", "token"])
        for t in unsourced:
            w.writerow([name_of(t), t])
    print(f"{len(unsourced)} items have no source in the game data (see unsourced_items.csv)")
    print(f"recipes: {len(recipe_rows)} item recipes + {len(piece_rows)} pieces; gatherable items: {len(gather_rows)}; "
          f"biome order: {', '.join(n for _, n in BIOMES)}")
