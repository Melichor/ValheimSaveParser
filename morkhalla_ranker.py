#!/usr/bin/env python3
"""morkhalla_ranker: rank a world's Mörkhalla dungeons by how close to the world center a Jotun invasion started there lands.

Reads a Valheim world save in the chunked format the game writes now (a folder holding _main.N.fwl2 and _main.N.db2).
Python 3, standard library only.

How the game places the invasion (Valheim 1.0.20: PersistentEventSystem, ZoneSystem, LocationProxy, UnityPlayer.so):
  * Breaking the Malicious Ice inside a Mörkhalla (location MorkBorg) starts the event jotun_invasion. The server tries up
    to 1000 spots and keeps the first one that passes its checks.
  * Each try draws Random.insideUnitCircle: two numbers from Unity's generator, each turned into t = (n & 0x7FFFFF) *
    1.1920930e-7. The first sets the angle, 2*pi*(1 - t), the second the length, m = sqrt(1 - t) (Unity's Range(a, b) is
    a*t + b*(1 - t)). The spot is (1000 + 11000*m) * (cos, sin) metres from the world center, so the distance comes from
    the second number alone. When m is exactly 0 (the low 23 bits all set) the spot is the world center itself.
  * Nothing seeds the generator for the event. The last thing that does is a location loading: its LocationProxy calls
    ZoneSystem.SpawnLocation, which runs Random.InitState(world seed + zoneX*4271 + zoneY*9187) and never restores the
    old state. The dungeon reseeds it when it loads, and so does every other location that loads around it. Between that
    reseed and the ice breaking come other draws (sounds, creature AI, the spawn system, your swings), a different
    number every time. Even the dungeon's own loading draws some right after its reseed, so 0 never really happens.
For each dungeon the script replays the generator from its reseed and works out where the invasion would land for every
number of draws in between, from 0 to --window - 1. The dungeon's score is the share of those that land within --target
metres. Terrain is ignored: a try is rejected only when it falls past the world edge, in the Ashlands or Deep North (both
fixed shapes), or within 450 m of the player at the dungeon. The game also rejects ocean, Mistlands, low and steep
ground; such a try moves on to the next pair of numbers, as the rejected ones here do.

    python3 morkhalla_ranker.py Woods3                       # a world by name, looked up in the usual save folders
    python3 morkhalla_ranker.py path/to/worlds/Woods3        # or the world's folder
    python3 morkhalla_ranker.py Woods3 --window 50 --target 3000 --detail 3 --show 20
    python3 morkhalla_ranker.py                              # list the worlds it can find
"""
import argparse
import glob
import gzip
import json
import math
import os
import re
import struct
import sys

LOCATION = "MorkBorg"                  # Mörkhalla's location prefab
MAX_TRIES = 1000                       # GenerateEventLocation gives up after this many
MIN_DISTANCE, MAX_DISTANCE = 1000.0, 12000.0   # jotun_invasion's minDistanceFromCenter / maxDistanceFromCenter
PLAYER_CLEARANCE = 450.0               # (maxRadius 300 + 150): no spot this close to a player
WORLD_EDGE = 10000.0                   # the terrain sinks into the ocean from here (WorldGenerator.GetBaseHeight)
ZONE_SIZE = 64.0
EXTRA_DRAWS = 2 * 200                  # numbers generated past the window up front, for the tries that get rejected

# Location prefab names, to name the hashes the save stores (every prefab under Assets/world/Locations, and BogWitch_Camp).
LOCATION_NAMES = """
    AbandonedLogCabin02 AbandonedLogCabin03 AbandonedLogCabin04 AncientUpgradeStation AshlandRuins BearCave
    BigRockClearing BogWitch_Camp Bonemass CharredFortress CharredRuins1 CharredRuins2 CharredRuins3 CharredRuins4
    CharredStone_Spawner CharredTowerRuins1 CharredTowerRuins1_dvergr CharredTowerRuins2 CharredTowerRuins3
    CombatRuin01 Crypt2 Crypt3 Crypt4 DevBedchamber DevCombatRange DevCombatRing DevDressingRoom DevFloor1 DevForge
    DevGarden DevGround1 DevGround2 DevHouse1 DevHouse2 DevHouse3 DevHouse4 DevHouse5 DevHouseStart DevKitchen
    DevMageRoom DevSoundTest DevWall1 DevWall2 DevWallAsh DN_Bossroom DN_gammeltrollFrac01 DN_gammeltrollFrac02
    DN_hut01 Dolmen01 Dolmen02 Dolmen03 Dragonqueen DrakeLorestone DrakeNest01 Eikthyrnir FaderLocation
    FimbulLocation01 FireHole FortressRuins FrozenShip01_DN FrozenShip02_DN FrozenShip03_DN GDKing GoblinCamp2
    GoblinCamp2_1 GoblinHut01 GoblinHut02 GoblinHut03 GoblinKing Grave1 Greydwarf_camp1 HalfBurried_ForestCrypt
    Hildir_camp Hildir_cave Hildir_crypt Hildir_plainsfortress HotSpring1 HotSpring2 HotSpring3 IcePond1
    InfestedTree01 LeviathanLava LumberCamp Mistlands_DvergrBossEntrance1 Mistlands_DvergrTownEntrance1
    Mistlands_DvergrTownEntrance2 Mistlands_Excavation1 Mistlands_Excavation2 Mistlands_Excavation3 Mistlands_Giant1
    Mistlands_Giant2 Mistlands_GuardTower1_new Mistlands_GuardTower1_ruined_new Mistlands_GuardTower1_ruined_new2
    Mistlands_GuardTower2_new Mistlands_GuardTower3_new Mistlands_GuardTower3_ruined_new Mistlands_Harbour1
    Mistlands_Lighthouse1_new Mistlands_RoadPost1 Mistlands_RockSpire1 Mistlands_Statue1 Mistlands_Statue2
    Mistlands_StatueGroup1 Mistlands_Swords1 Mistlands_Swords2 Mistlands_Swords3 Mistlands_Viaduct1
    Mistlands_Viaduct2 MorgenHole1 MorgenHole2 MorgenHole3 MorkBorg MountainCave02 MountainGrave01 MountainWell1
    NorthMemorialPlace NorthVillage PlaceofMystery1 PlaceofMystery2 PlaceofMystery3 Ruin1 Ruin2 Ruin3
    Runestone_Ashlands Runestone_BlackForest Runestone_Boars Runestone_DeepNorth Runestone_Draugr
    Runestone_Greydwarfs Runestone_Meadows Runestone_Mistlands Runestone_Mountains Runestone_Plains Runestone_Swamps
    ShipSetting01 ShipSetting02 ShipSetting03 ShipWreck01 ShipWreck01_DN ShipWreck02 ShipWreck02_DN ShipWreck03
    ShipWreck04 StartTemple StoneCircle StoneHenge1 StoneHenge2 StoneHenge3 StoneHenge4 StoneHenge5 StoneHenge6
    StoneHouse1_heath StoneHouse2_heath StoneHouse3 StoneHouse4 StoneHouse5_heath StoneTower1 StoneTower3
    StoneTowerRuins03 StoneTowerRuins04 StoneTowerRuins05 StoneTowerRuins05_leet StoneTowerRuins07
    StoneTowerRuins07_sunk StoneTowerRuins08 StoneTowerRuins08_sunk StoneTowerRuins09 StoneTowerRuins09_sunk
    StoneTowerRuins10 StoneTowerRuins10_sunk SulfurArch SunkenCrypt4 SwampHut1 SwampHut1_1 SwampHut2 SwampHut2_1
    SwampHut3 SwampHut3_1 SwampHut4 SwampHut5 SwampRuin1 SwampRuin2 SwampWell1 TarPit1 TarPit1_1 TarPit2 TarPit2_1
    TarPit3 TarPit3_1 TheDarkestHole TheHole01 TrollCave02 Vendor_BlackForest VoltureNest Waymarker01 Waymarker02
    WoodFarm1 WoodHouse1 WoodHouse10 WoodHouse11 WoodHouse12 WoodHouse13 WoodHouse2 WoodHouse3 WoodHouse4 WoodHouse5
    WoodHouse6 WoodHouse7 WoodHouse8 WoodHouse9 WoodVillage1 WoodVillage2
""".split()
DISPLAY_NAMES = {"MorkBorg": "Mörkhalla"}

# Where the game keeps worlds: its own folder, and Steam Cloud's copy.
SAVE_ROOTS = [
    "~/.config/unity3d/IronGate/Valheim/worlds_local",
    "~/.steam/steam/userdata/*/892970/remote/worlds",
    "~/.local/share/Steam/userdata/*/892970/remote/worlds",
    "~/AppData/LocalLow/IronGate/Valheim/worlds_local",
    "C:/Program Files (x86)/Steam/userdata/*/892970/remote/worlds",
    "~/Library/Application Support/IronGate/Valheim/worlds_local",
]


class WorldError(Exception):
    """The input is not a world this tool can read."""


# ---------------------------------------------------------------------------------------------------------------
# The parts of the game this depends on
# ---------------------------------------------------------------------------------------------------------------

M32 = 0xFFFFFFFF
F32 = struct.Struct("<f")
VALUE_SCALE = F32.unpack(bytes.fromhex("01000034"))[0]   # the constant UnityPlayer.so multiplies the low 23 bits by
TWO_PI = F32.unpack(bytes.fromhex("db0fc940"))[0]        # 2*pi as UnityPlayer.so stores it


def f32(x):
    """Round to a 32-bit float, as the game's float arithmetic does."""
    return F32.unpack(F32.pack(x))[0]


def s32(x):
    x &= M32
    return x - (1 << 32) if x >= 1 << 31 else x


def stable_hash(text):
    """string.GetStableHashCode() from the game."""
    a = b = 5381
    for i in range(0, len(text), 2):
        a = s32(((a << 5) + a) ^ ord(text[i]))
        if i == len(text) - 1:
            break
        b = s32(((b << 5) + b) ^ ord(text[i + 1]))
    return s32(a + b * 1566083941)


def unity_numbers(seed, count):
    """The first `count` raw numbers of UnityEngine.Random after InitState(seed): a xorshift128, as in UnityPlayer.so."""
    s0 = seed & M32
    s1 = (s0 * 0x6C078965 + 1) & M32
    s2 = (s1 * 0x6C078965 + 1) & M32
    s3 = (s2 * 0x6C078965 + 1) & M32
    out = []
    for _ in range(count):
        t = (s0 ^ (s0 << 11)) & M32
        s0, s1, s2, s3 = s1, s2, s3, (t ^ s3 ^ (t >> 8) ^ (s3 >> 19)) & M32
        out.append(s3)
    return out


def unit(n):
    """A raw number as the float t in [0, 1] that Random.value and Random.Range start from."""
    return f32((n & 0x7FFFFF) * VALUE_SCALE)


def spot(a, b):
    """The spot GenerateEventLocation tries for the two numbers Random.insideUnitCircle draws (GetRandomUnitCircle)."""
    angle = f32(f32(1.0 - unit(a)) * TWO_PI)
    m = math.sqrt(f32(1.0 - unit(b)))
    if m <= 1e-5:
        return 0.0, 0.0           # normalizing the zero vector gives zero, so nothing pushes the spot out to 1000 m
    d = MIN_DISTANCE + (MAX_DISTANCE - MIN_DISTANCE) * m
    return d * math.cos(angle), d * math.sin(angle)


def world_angle(x, z):
    return math.sin(math.atan2(x, z) * 20.0)


def outside_allowed_area(x, z, edge):
    """True when the spot can never pass, whatever the terrain: past the edge, or in the Ashlands or the Deep North."""
    if math.hypot(x, z) > edge:
        return True
    wobble = world_angle(x, z) * 100.0
    return math.hypot(x, z - 4000.0) > 12000.0 + wobble or math.hypot(x, z + 4000.0) > 12000.0 + wobble


def zone_of(x, z):
    return math.floor((x + 32.0) / ZONE_SIZE), math.floor((z + 32.0) / ZONE_SIZE)


def location_seed(world_seed, zone):
    """The seed ZoneSystem.PlaceLocations gives the location in a zone, which its LocationProxy keeps."""
    return s32(world_seed + zone[0] * 4271 + zone[1] * 9187)


def loaded_zones(zone, level):
    """The zones whose objects load around a player in `zone` (ZDOMan.FindSectorObjects; location proxies are not
    'distant', so only the near distance counts). `level` is the Simulation Distance setting, as SimulationDistance maps it."""
    near, square = (1, True) if level == 0 else (2, level == 2) if level <= 2 else (level, False)
    return {(zone[0] + dx, zone[1] + dy) for dy in range(-near, near + 1) for dx in range(-near, near + 1)
            if square or dx * dx + dy * dy < (near + 0.5) ** 2}


# ---------------------------------------------------------------------------------------------------------------
# Reading the world
# ---------------------------------------------------------------------------------------------------------------

class Reader:
    def __init__(self, data, pos=0):
        self.d, self.p = data, pos

    def take(self, fmt):
        v = struct.unpack_from("<" + fmt, self.d, self.p)
        self.p += struct.calcsize("<" + fmt)
        return v[0] if len(v) == 1 else v

    def skip(self, n):
        if n < 0 or self.p + n > len(self.d):
            raise WorldError("unexpected end of the save")
        self.p += n

    def string(self):
        n = shift = 0
        while True:
            b = self.d[self.p]
            self.p += 1
            n |= (b & 0x7F) << shift
            shift += 7
            if b < 0x80:
                break
        s = self.d[self.p:self.p + n].decode("utf8")
        self.p += n
        return s


def world_folders():
    """name -> folder of every chunked world save in the usual places."""
    found = {}
    for root in SAVE_ROOTS:
        for base in glob.glob(os.path.expanduser(root)):
            for folder in sorted(glob.glob(os.path.join(base, "*", "_main.*.fwl2"))):
                found.setdefault(os.path.basename(os.path.dirname(folder)), os.path.dirname(folder))
    return found


def find_save(target):
    """(path of _main.N.fwl2, path of _main.N.db2) for a world name, a world folder or one of its _main files."""
    if os.path.isfile(target):
        if target.endswith((".db", ".fwl")):
            raise WorldError("this is a world in the old single-file format. Mörkhalla came with the Deep North update, "
                             "and the game saves those worlds as a folder with _main.N.db2 files; pass that folder")
        m = re.search(r"_main\.(\d+)\.(fwl2|db2|chunks|ok)$", target)
        if not m:
            raise WorldError("expected a world folder or one of its _main.N.fwl2 / _main.N.db2 files")
        folder, numbers = os.path.dirname(target) or ".", [int(m.group(1))]
    else:
        folder = target if os.path.isdir(target) else world_folders().get(target)
        if folder is None:
            raise WorldError(f"no world folder or world named {target!r}")
        numbers = sorted({int(m.group(1)) for f in os.listdir(folder) if (m := re.match(r"_main\.(\d+)\.fwl2$", f))},
                         reverse=True)
        if not numbers:
            raise WorldError(f"{folder} holds no _main.N.fwl2 file")
        # The game loads the newest save number whose files are all there; .ok is written last.
        complete = [n for n in numbers if os.path.exists(os.path.join(folder, f"_main.{n}.ok"))]
        numbers = complete + [n for n in numbers if n not in complete]
    for n in numbers:
        fwl, db = (os.path.join(folder, f"_main.{n}.{ext}") for ext in ("fwl2", "db2"))
        if os.path.exists(fwl) and os.path.exists(db):
            return fwl, db
    raise WorldError("no save with both _main.N.fwl2 and _main.N.db2 (the world was never saved with data)")


def read_meta(path):
    """The world's name and seed from _main.N.fwl2 (World.LoadWorld)."""
    data = open(path, "rb").read()
    r = Reader(data, 4)
    version = r.take("i")
    name, seed_name, seed = r.string(), r.string(), r.take("i")
    return {"version": version, "name": name, "seedName": seed_name, "seed": seed}


def read_locations(path):
    """Every location the world placed: (name hash, x, y, z, visited), from _main.N.db2 (ZoneSystem.Load)."""
    r = Reader(open(path, "rb").read())
    r.take("i")                               # world version
    r.take("d")                               # net time
    size = r.take("i")
    try:
        z = Reader(gzip.decompress(r.d[r.p:r.p + size]))
    except (OSError, EOFError) as e:
        raise WorldError(f"cannot unpack the zone data: {e}")
    z.skip(4 * z.take("i"))                   # generated zones, two shorts each
    z.take("i")                               # location version
    for _ in range(z.take("i")):              # global keys
        z.string()
    z.take("?")                               # locations generated
    out = []
    for _ in range(z.take("i")):
        h, x, y, zz, visited = z.take("i"), *z.take("fff"), z.take("?")
        out.append((h, x, y, zz, visited))
    return out


# ---------------------------------------------------------------------------------------------------------------
# Where the invasion lands
# ---------------------------------------------------------------------------------------------------------------

def unity_numbers_after(numbers, count):
    """`count` more numbers continuing a stream from unity_numbers (its state is its last four numbers)."""
    s0, s1, s2, s3 = numbers[-4:]
    out = []
    for _ in range(count):
        t = (s0 ^ (s0 << 11)) & M32
        s0, s1, s2, s3 = s1, s2, s3, (t ^ s3 ^ (t >> 8) ^ (s3 >> 19)) & M32
        out.append(s3)
    return out


def landings(seed, player, window, edge):
    """For each number k of draws between the reseed and the ice breaking (0 <= k < window): (x, z, tries) of the spot
    the invasion takes, or None when all 1000 tries fail."""
    numbers = unity_numbers(seed, window + EXTRA_DRAWS)
    passes = {}                               # first number of a try -> its spot, or None when it is rejected
    px, pz = player

    def attempt(i):
        if i not in passes:
            while i + 1 >= len(numbers):
                numbers.extend(unity_numbers_after(numbers, EXTRA_DRAWS))
            x, z = spot(numbers[i], numbers[i + 1])
            ok = not outside_allowed_area(x, z, edge) and (x - px) ** 2 + (z - pz) ** 2 >= PLAYER_CLEARANCE ** 2
            passes[i] = (x, z) if ok else None
        return passes[i]

    out = []
    for k in range(window):
        for t in range(MAX_TRIES):
            s = attempt(k + 2 * t)
            if s is not None:
                out.append((s[0], s[1], t + 1))
                break
        else:
            out.append(None)
    return out


def summarize(seed, player, window, target, edge, keep=0):
    lands = landings(seed, player, window, edge)
    dist = sorted(math.hypot(p[0], p[1]) if p else math.inf for p in lands)
    first = lands[0]
    out = {"reseed": seed,
           "hit": sum(1 for d in dist if d <= target) / window,
           "median": dist[(window - 1) // 2],
           "noDraws": None if first is None else {"x": round(first[0]), "z": round(first[1]),
                                                  "distance": round(math.hypot(first[0], first[1]))}}
    if keep:
        out["landings"] = [None if p is None else {"draws": k, "x": round(p[0]), "z": round(p[1]),
                                                   "distance": round(math.hypot(p[0], p[1])), "tries": p[2]}
                           for k, p in enumerate(lands[:keep])]
    return out


def baseline(target, edge, steps=720):
    """The share of invasions within `target` for a reseed whose numbers are as random as can be, over the same rules."""
    hit = total = 0.0
    for j in range(steps):
        m = (j + 0.5) / steps                 # 1 - t is uniform, so m = sqrt(1 - t) has density 2m
        d = MIN_DISTANCE + (MAX_DISTANCE - MIN_DISTANCE) * m
        if d > edge:
            break
        if d <= 7900:                         # the Ashlands and the Deep North start farther out in every direction
            share = 1.0
        else:
            share = sum(not outside_allowed_area(d * math.cos(a), d * math.sin(a), edge)
                        for a in (2 * math.pi * (i + 0.5) / steps for i in range(steps))) / steps
        total += m * share
        if d <= target:
            hit += m * share
    return hit / total


def rank(fwl, db, location, window, target, edge, level, show):
    meta = read_meta(fwl)
    locs = read_locations(db)
    names = {stable_hash(n): n for n in LOCATION_NAMES}
    wanted = stable_hash(location)
    by_zone = {zone_of(x, z): (h, x, z, visited) for h, x, _, z, visited in locs}
    dungeons = []
    for h, x, _, z, visited in locs:
        if h != wanted:
            continue
        zone = zone_of(x, z)
        own = summarize(location_seed(meta["seed"], zone), (x, z), window, target, edge, keep=show)
        others = []
        for oz in sorted(loaded_zones(zone, level) - {zone}):
            if oz in by_zone:
                oh, ox, ozz, _ = by_zone[oz]
                o = summarize(location_seed(meta["seed"], oz), (x, z), window, target, edge)
                others.append({"name": names.get(oh, f"#{oh}"), "x": round(ox), "z": round(ozz), **o})
        dungeons.append({"x": round(x), "z": round(z), "zone": list(zone), "visited": visited,
                         "fromCenter": round(math.hypot(x, z)), **own, "others": others,
                         "worst": min([own["hit"]] + [o["hit"] for o in others])})
    return {"world": meta["name"], "seedName": meta["seedName"], "seed": meta["seed"],
            "location": DISPLAY_NAMES.get(location, location), "window": window, "target": target,
            "simulationDistance": level, "baseline": round(baseline(target, edge), 4), "dungeons": dungeons}


# ---------------------------------------------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------------------------------------------

def metres(d):
    return "never" if d == math.inf else f"{d:.0f} m"


def show(res, sort, detail):
    ds = res["dungeons"]
    loc = res["location"]
    if not ds:
        print(f"{res['world']}: no {loc} in this world (it has to be generated by a game version with the Deep North)")
        return
    key = {"hit": lambda d: (-d["hit"], d["median"]), "worst": lambda d: (-d["worst"], -d["hit"]),
           "nodraws": lambda d: d["noDraws"]["distance"] if d["noDraws"] else math.inf,
           "center": lambda d: d["fromCenter"]}[sort]
    ds = sorted(ds, key=key)
    visited = sum(1 for d in ds if d["visited"])
    print(f"{res['world']} (seed {res['seedName']}): {len(ds)} {loc} locations, {visited or 'none'} visited")
    print(f"Counting 0 to {res['window'] - 1} draws between the dungeon's reseed and the ice breaking:")
    print(f"  hit       share of those that land within {res['target']:.0f} m of the center "
          f"(a fully random reseed averages {res['baseline']:.1%})")
    print("  median    the middle distance;  no draws: where it lands with none in between")
    print(f"  others    other locations that load with the dungeon (Simulation Distance {res['simulationDistance']}); "
          "each reseeds too, and the last to load counts")
    print("  worst     the lowest hit among the dungeon and those others")
    print()
    print(f"{'#':>3}  {'dungeon at (x, z)':<18} {'from center':>11}  {'reseed':>11}  {'hit':>6}  {'median':>8}  "
          f"{'no draws':>8}  {'others':>6}  {'worst':>6}")
    for i, d in enumerate(ds, 1):
        nd = metres(d["noDraws"]["distance"]) if d["noDraws"] else "never"
        print(f"{i:>3}  ({d['x']:>6}, {d['z']:>6})  {d['fromCenter']:>9} m  {d['reseed']:>11}  {d['hit']:>6.1%}  "
              f"{metres(d['median']):>8}  {nd:>8}  {len(d['others']):>6}  {d['worst']:>6.1%}")
    for i, d in enumerate(ds[:detail], 1):
        print()
        print(f"#{i}  {loc} at ({d['x']}, {d['z']}), zone ({d['zone'][0]}, {d['zone'][1]}), reseed {d['reseed']}")
        print(f"     {'draws':>5}  {'lands at (x, z)':<18} {'distance':>9}  tries")
        for p in d.get("landings", []):
            if p is None:
                print("            no spot in 1000 tries")
            else:
                print(f"     {p['draws']:>5}  ({p['x']:>6}, {p['z']:>6})  {p['distance']:>7} m  {p['tries']:>5}")
        for o in d["others"]:
            print(f"     also loads: {o['name']} at ({o['x']}, {o['z']}), reseed {o['reseed']}, hit {o['hit']:.1%}")


def main():
    ap = argparse.ArgumentParser(description="Rank a world's Mörkhalla dungeons by how close to the world center a "
                                 "Jotun invasion started there lands.")
    ap.add_argument("world", nargs="?", help="a world name, its save folder, or its _main.N.fwl2 / .db2 file "
                    "(leave out to list the worlds found)")
    ap.add_argument("--window", type=int, default=200, metavar="N",
                    help="how many different numbers of draws between the reseed and the ice breaking to count, "
                    "from 0 to N-1 (default: 200)")
    ap.add_argument("--target", type=float, default=5000, metavar="M", help="a hit lands within this many metres "
                    "of the world center (default: 5000)")
    ap.add_argument("--edge", type=float, default=WORLD_EDGE, metavar="M", help="reject tries farther out than this, "
                    "where the world is ocean (default: 10000)")
    ap.add_argument("--simdist", type=int, default=2, metavar="LEVEL", help="the Simulation Distance graphics setting "
                    "(the server's, in multiplayer), which decides which other locations load with the dungeon "
                    "(default: 2, the original 5x5 zones)")
    ap.add_argument("--sort", choices=["hit", "worst", "nodraws", "center"], default="hit",
                    help="order by the dungeon's own hit share (default), by the worst one counting the locations "
                    "that load with it, by where the invasion lands with no draws in between, or by the dungeon's "
                    "distance from the world center")
    ap.add_argument("--detail", type=int, default=3, metavar="N", help="show the first landings of the top N dungeons "
                    "(default: 3)")
    ap.add_argument("--show", type=int, default=10, metavar="N", help="how many landings to show for each (default: 10)")
    ap.add_argument("--location", default=LOCATION, help=f"rank another location type by its prefab name "
                    f"(default: {LOCATION}, which is Mörkhalla)")
    ap.add_argument("--json", action="store_true", help="print the result as JSON")
    args = ap.parse_args()
    if args.window < 1 or args.show < 0 or args.detail < 0:
        ap.error("--window must be at least 1, --show and --detail at least 0")
    if args.world is None:
        found = world_folders()
        if not found:
            ap.error("no world saves found in the usual folders; pass the world's folder")
        print("Worlds found:")
        for name, folder in sorted(found.items(), key=lambda kv: kv[0].lower()):
            print(f"  {name:<40} {folder}")
        return
    try:
        fwl, db = find_save(args.world)
        res = rank(fwl, db, args.location, args.window, args.target, args.edge, args.simdist,
                   args.show if args.detail else 0)
    except OSError as e:
        ap.error(f"cannot read {args.world}: {e.strerror or e}")
    except (WorldError, struct.error, UnicodeDecodeError) as e:
        ap.error(f"{args.world}: {e}")
    if args.json:
        for d in res["dungeons"]:
            d["median"] = None if d["median"] == math.inf else round(d["median"])
            for o in d["others"]:
                o["median"] = None if o["median"] == math.inf else round(o["median"])
        print(json.dumps(res, indent=1, ensure_ascii=False))
    else:
        show(res, args.sort, args.detail)


if __name__ == "__main__":
    sys.exit(main())
