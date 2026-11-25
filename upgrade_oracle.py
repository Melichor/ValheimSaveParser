#!/usr/bin/env python3
"""upgrade_oracle: predict how many times an item can be upgraded at the Forge of Potential before it breaks.

Reads a Valheim character file (.fch, profile version 46 and up, player data version 34). Python 3, standard library only.

How the game decides an upgrade (Valheim 1.0.30, InventoryGui.DoCrafting and Player.GetItemUpgradeChance):
  * Each attempt is keyed by the item's prefab name hash plus the level it is being upgraded to.
  * The roll is Unity's Random.value after Random.InitState(seed). The seed is the one stored in the character for that
    key, or, when the key was never used, m_dateCreated.GetHashCode() plus the key.
  * After the roll the game stores a new random seed for the key, so the next attempt on the same key is a different roll.
  * The attempt succeeds when UPGRADE_CHANCE >= roll, destroys the item when BREAK_CHANCE >= 1 - roll, and otherwise
    lowers the item by one level.
The character part of the default seed is its creation date. The save keeps it as Unix seconds (UTC); the game loads it
as DateTimeOffset.FromUnixTimeSeconds(s).LocalDateTime, i.e. in the time zone of the machine running the game (with the
offset in force at that instant), and hashes the local ticks: (int)ticks ^ (int)(ticks >> 32). So the rolls depend on
the creation stamp, the game machine's time zone and the seeds saved in the file, which is what this script replays.
(Valheim 1.0.20 to 1.0.29 used the hash of the character name instead; the web page's name tools still follow that.)
Unity's generator (a xorshift128 seeded as s[i] = s[i-1] * 1812433253 + 1) was taken from the game's UnityPlayer.so.

    python3 upgrade_oracle.py Character.fch                  # the upgradable items in the inventory
    python3 upgrade_oracle.py Character.fch --tz Europe/Prague   # ...if the game runs in another zone than this machine
    python3 upgrade_oracle.py Character.fch --item SwordIron # a fresh item, or --quality N for one that is already upgraded
    python3 upgrade_oracle.py Character.fch --all            # every upgradable item from level 1
    python3 upgrade_oracle.py Character.fch --check          # compare the saved seeds with what the generator predicts
    python3 upgrade_oracle.py --created "2026-11-25 14:03:07" --item SwordIron   # a new character created at that local time
    python3 upgrade_oracle.py --item SwordIron --quality 1 --findtime 6         # creation times that give exactly 6 upgrades
    python3 upgrade_oracle.py --item SwordIron --quality 4 --findtime 5 --copies 2   # ...and a second copy that gets past the break
"""
import argparse
import datetime
import json
import struct
import sys

PROFILE_MIN_VERSION = 46
PLAYER_DATA_VERSION = 34
STAT_COUNT = 205
SET_COUNT = 10
# The most upgrades a new character can get in a row on its first attempts. The level keys are consecutive numbers, so the
# seeds of consecutive levels are consecutive too, and Unity's generator gives correlated first rolls for those. Trying
# every one of the 2^32 possible starting seeds gave: 0 upgrades 35.0%, 1: 31.6%, 2: 16.8%, 3: 9.9%, 4: 6.7%,
# 5: 0.014%, 6: 0.0076%, 7: 0.0035%, 8: 0.0005%, and never more than 8.
MAX_FIRST_RUN = 8
MAX_ATTEMPTS = 200          # stop a run that somehow never breaks

# BEGIN GENERATED UPGRADABLE (tools/update_upgrade_items.py rewrites everything up to END GENERATED UPGRADABLE)
# Chance that one upgrade attempt succeeds, and the chance (checked next) that a failed attempt destroys the item.
UPGRADE_CHANCE = 0.65
BREAK_CHANCE = 1.0
# Prefab name -> display name of every item that can be upgraded at the Forge of Potential.
UPGRADABLE = {
    'ArmorAshlandsMediumChest': 'Breastplate of Ask',
    'ArmorAshlandsMediumlegs': 'Trousers of Ask',
    'ArmorBerserkerChest': 'Patterns of the Bear',
    'ArmorBerserkerLegs': 'Loincloth of the Bear',
    'ArmorBerserkerUndeadChest': 'Vilebone Cage',
    'ArmorBerserkerUndeadLegs': 'Vilebone Drapes',
    'ArmorBronzeChest': 'Bronze Plate Tunic',
    'ArmorBronzeLegs': 'Bronze Plate Leggings',
    'ArmorCarapaceChest': 'Carapace Breastplate',
    'ArmorCarapaceLegs': 'Carapace Greaves',
    'ArmorDeepNorthHeavyChest': 'Breastplate of the Protector',
    'ArmorDeepNorthHeavylegs': 'Trousers of the Protector',
    'ArmorDeepNorthMageChest': 'Robes of the Caller',
    'ArmorDeepNorthMagelegs': 'Trousers of the Caller',
    'ArmorDeepNorthMediumChest': 'Chestpiece of the Vanguard',
    'ArmorDeepNorthMediumlegs': 'Trousers of the Vanguard',
    'ArmorFenringChest': 'Fenris Coat',
    'ArmorFenringLegs': 'Fenris Leggings',
    'ArmorFlametalChest': 'Flametal Breastplate',
    'ArmorFlametalLegs': 'Flametal Greaves',
    'ArmorIronChest': 'Iron Scale Mail',
    'ArmorIronLegs': 'Iron Greaves',
    'ArmorLeatherChest': 'Leather Tunic',
    'ArmorLeatherLegs': 'Leather Trousers',
    'ArmorLoxChest': 'Lox Fur Jacket',
    'ArmorLoxLegs': 'Lox Fur Trousers',
    'ArmorMageChest': 'Eitr-weave Robe',
    'ArmorMageChest_Ashlands': 'Robes of Embla',
    'ArmorMageLegs': 'Eitr-weave Trousers',
    'ArmorMageLegs_Ashlands': 'Trousers of Embla',
    'ArmorPaddedCuirass': 'Padded Cuirass',
    'ArmorPaddedGreaves': 'Padded Greaves',
    'ArmorRagsChest': 'Rag Tunic',
    'ArmorRagsLegs': 'Rag Trousers',
    'ArmorRootChest': 'Root Harnesk',
    'ArmorRootLegs': 'Root Leggings',
    'ArmorTrollLeatherChest': 'Troll Leather Tunic',
    'ArmorTrollLeatherLegs': 'Troll Leather Trousers',
    'ArmorWolfChest': 'Wolf Hide Chestpiece',
    'ArmorWolfLegs': 'Wolf Hide Trousers',
    'AtgeirBlackmetal': 'Black Metal Atgeir',
    'AtgeirBronze': 'Bronze Atgeir',
    'AtgeirGold': 'Nord Atgeir',
    'AtgeirGold_BloodLightning': 'Thunderblood Atgeir',
    'AtgeirGold_FrostFire': 'Frostfire Atgeir',
    'AtgeirHimminAfl': 'Himminafl',
    'AtgeirIron': 'Iron Atgeir',
    'AxeBerzerkr': 'Berserkir Axes',
    'AxeBerzerkrBlood': 'Bleeding Berserkir Axes',
    'AxeBerzerkrLightning': 'Thundering Berserkir Axes',
    'AxeBerzerkrNature': 'Primal Berserkir Axes',
    'AxeBlackMetal': 'Black Metal Axe',
    'AxeBronze': 'Bronze Axe',
    'AxeEarly': 'Early Axes',
    'AxeFlint': 'Flint Axe',
    'AxeGold': 'Nord Axe',
    'AxeGold_BloodLightning': 'Thunderblood Axe',
    'AxeGold_FrostFire': 'Frostfire Axe',
    'AxeIron': 'Iron Axe',
    'AxeJotunBane': 'Jotun Bane',
    'AxeStone': 'Stone Axe',
    'Battleaxe': 'Battleaxe',
    'BattleaxeBlackmetal': 'Black Metal Battleaxe',
    'BattleaxeCrystal': 'Crystal Battleaxe',
    'BattleaxeGold': 'Nord Greataxe',
    'BattleaxeGold_BloodLightning': 'Thunderblood Greataxe',
    'BattleaxeGold_FrostFire': 'Frostfire Greataxe',
    'BattleaxeSkullSplittur': 'Skull Splittur',
    'Bow': 'Crude Bow',
    'BowAshlands': 'Ash Fang',
    'BowAshlandsBlood': 'Blood Fang',
    'BowAshlandsRoot': 'Root Fang',
    'BowAshlandsStorm': 'Storm Fang',
    'BowDraugrFang': 'Draugr Fang',
    'BowFineWood': 'Finewood Bow',
    'BowGold': 'Nord Bow',
    'BowGold_BloodLightning': 'Thunderblood Bow',
    'BowGold_FrostFire': 'Frostfire Bow',
    'BowHuntsman': 'Huntsman Bow',
    'BowSpineSnap': 'Spinesnap',
    'CapeAsh': 'Ashen Cape',
    'CapeAsksvin': 'Asksvin Cloak',
    'CapeDeepNorth': 'Moose Hide Cape',
    'CapeDeepNorthMage': 'Cape of the Caller',
    'CapeDeerHide': 'Deer Hide Cape',
    'CapeFeather': 'Feather Cape',
    'CapeLinen': 'Linen Cape',
    'CapeLox': 'Lox Cape',
    'CapeOdin': 'Cape of Oden',
    'CapeTrollHide': 'Troll Hide Cape',
    'CapeWolf': 'Wolf Fur Cape',
    'Club': 'Club',
    'CrossbowArbalest': 'Arbalest',
    'CrossbowGold': 'Nord Crossbow',
    'CrossbowGold_BloodLightning': 'Thunderblood Crossbow',
    'CrossbowGold_FrostFire': 'Frostfire Crossbow',
    'CrossbowRipper': 'Ripper',
    'CrossbowRipperBlood': 'Wound Ripper',
    'CrossbowRipperLightning': 'Storm Ripper',
    'CrossbowRipperNature': 'Root Ripper',
    'Cultivator': 'Cultivator',
    'FistBjornClaw': 'Paws of the Bear',
    'FistBjornUndeadClaw': 'Vilebone Maulclaws',
    'FistFenrirClaw': 'Flesh Rippers',
    'FistGold': 'Nord Knucklechains',
    'FistGold_BloodLightning': 'Thunderblood Knucklechains',
    'FistGold_FrostFire': 'Frostfire Knucklechains',
    'Hammer': 'Hammer',
    'HelmetAshlandsMediumHood': 'Hood of Ask',
    'HelmetBerserkerHood': 'Headdress of the Bear',
    'HelmetBerserkerUndead': 'Vilebone Visage',
    'HelmetBronze': 'Bronze Helmet',
    'HelmetCarapace': 'Carapace Helmet',
    'HelmetCelebration': 'Celebratory Cap',
    'HelmetDNHeavy': 'Helmet of the Protector',
    'HelmetDNMage': 'Headdress of the Caller',
    'HelmetDNMediumHood': 'Hood of the Vanguard',
    'HelmetDrake': 'Drake Helmet',
    'HelmetFenring': 'Fenris Hood',
    'HelmetFishingHat': 'Fishing Hat',
    'HelmetFlametal': 'Flametal Helmet',
    'HelmetIron': 'Iron Helmet',
    'HelmetLeather': 'Leather Helmet',
    'HelmetLox': 'Lox Fur Hood',
    'HelmetMage': 'Eitr-weave Hood',
    'HelmetMage_Ashlands': 'Hood of Embla',
    'HelmetOdin': 'Hood of Oden',
    'HelmetPadded': 'Padded Helmet',
    'HelmetPointyHat': 'Pointy Hat',
    'HelmetRoot': 'Root Mask',
    'HelmetTrollLeather': 'Troll Leather Hood',
    'Hoe': 'Hoe',
    'KnifeBlackMetal': 'Black Metal Knife',
    'KnifeChitin': 'Abyssal Razor',
    'KnifeCopper': 'Copper Knife',
    'KnifeFlint': 'Flint Knife',
    'KnifeGold': 'Nord Dagger',
    'KnifeGold_BloodLightning': 'Thunderblood Dagger',
    'KnifeGold_FrostFire': 'Frostfire Dagger',
    'KnifeSilver': 'Silver Knife',
    'KnifeSkollAndHati': 'Skoll and Hati',
    'MaceBronze': 'Bronze Mace',
    'MaceEldner': 'Flametal Mace',
    'MaceEldnerBlood': 'Bloodgeon',
    'MaceEldnerLightning': 'Storm Star',
    'MaceEldnerNature': 'Klossen',
    'MaceGold': 'Nord Mace',
    'MaceGold_BloodLightning': 'Thunderblood Mace',
    'MaceGold_FrostFire': 'Frostfire Mace',
    'MaceIron': 'Iron Mace',
    'MaceNeedle': 'Porcupine',
    'MaceSilver': 'Frostner',
    'PickaxeBlackMetal': 'Black Metal Pickaxe',
    'PickaxeBronze': 'Bronze Pickaxe',
    'PickaxeIron': 'Iron Pickaxe',
    'Scythe': 'Scythe',
    'ShieldBanded': 'Banded Shield',
    'ShieldBlackmetal': 'Black Metal Shield',
    'ShieldBlackmetalTower': 'Black Metal Tower Shield',
    'ShieldBoneTower': 'Bone Tower Shield',
    'ShieldBronzeBuckler': 'Bronze Buckler',
    'ShieldCarapace': 'Carapace Shield',
    'ShieldCarapaceBuckler': 'Carapace Buckler',
    'ShieldFlametal': 'Flametal Shield',
    'ShieldFlametalTower': 'Flametal Tower Shield',
    'ShieldGold': 'Nord Shield',
    'ShieldGoldBuckler': 'Nord Buckler',
    'ShieldGoldTower': 'Nord Greatshield',
    'ShieldIronBuckler': 'Iron Buckler',
    'ShieldIronTower': 'Iron Tower Shield',
    'ShieldRoots': 'Shield of Roots',
    'ShieldSerpentscale': 'Serpent Scale Shield',
    'ShieldSilver': 'Silver Shield',
    'ShieldWood': 'Wood Shield',
    'ShieldWoodTower': 'Wood Tower Shield',
    'Shovel': 'Snow Shovel',
    'SledgeDemolisher': 'Demolisher',
    'SledgeGold': 'Nord Sledge',
    'SledgeGold_BloodLightning': 'Thunderblood Sledge',
    'SledgeGold_FrostFire': 'Frostfire Sledge',
    'SledgeIron': 'Iron Sledge',
    'SledgeStagbreaker': 'Stagbreaker',
    'SpearBronze': 'Bronze Spear',
    'SpearCarapace': 'Carapace Spear',
    'SpearElderbark': 'Ancient Bark Spear',
    'SpearFlint': 'Flint Spear',
    'SpearGold': 'Nord Spear',
    'SpearGold_BloodLightning': 'Thunderblood Spear',
    'SpearGold_FrostFire': 'Frostfire Spear',
    'SpearSplitner': 'Splitnir',
    'SpearSplitner_Blood': 'Splitnir the Bleeding',
    'SpearSplitner_Lightning': 'Splitnir the Storming',
    'SpearSplitner_Nature': 'Splitnir the Primal',
    'SpearWolfFang': 'Fang Spear',
    'StaffClusterbomb': 'Staff of Fracturing',
    'StaffFireball': 'Staff of Embers',
    'StaffFrostOrbs': 'Northern Vengeance',
    'StaffGreenRoots': 'Staff of the Wild',
    'StaffIceShards': 'Staff of Frost',
    'StaffLightning': 'Dundr',
    'StaffOrbofAhri': 'Echo Spike',
    'StaffRedTroll': 'Trollstav',
    'StaffShield': 'Staff of Protection',
    'StaffSkeleton': 'Dead Raiser',
    'StaffSpiritCaller': 'Spirit Caller',
    'StaffThunderBlood': 'Lightning Strike',
    'SwordBlackmetal': 'Black Metal Sword',
    'SwordBronze': 'Bronze Sword',
    'SwordDyrnwyn': 'Dyrnwyn',
    'SwordGold': 'Nord Sword',
    'SwordGold_BloodLightning': 'Thunderblood Sword',
    'SwordGold_FrostFire': 'Frostfire Sword',
    'SwordIron': 'Iron Sword',
    'SwordMistwalker': 'Mistwalker',
    'SwordNiedhogg': 'Nidhögg',
    'SwordNiedhoggBlood': 'Nidhögg the Bleeding',
    'SwordNiedhoggLightning': 'Nidhögg the Thundering',
    'SwordNiedhoggNature': 'Nidhögg the Primal',
    'SwordSilver': 'Silver Sword',
    'SwordWood': 'Wooden Sword',
    'THSwordGold': 'Nord Greatsword',
    'THSwordGold_BloodLightning': 'Thunderblood Greatsword',
    'THSwordGold_FrostFire': 'Frostfire Greatsword',
    'THSwordKrom': 'Krom',
    'THSwordSlayer': 'Slayer',
    'THSwordSlayerBlood': 'Brutal Slayer',
    'THSwordSlayerLightning': 'Scourging Slayer',
    'THSwordSlayerNature': 'Primal Slayer',
}
# END GENERATED UPGRADABLE


class SaveError(Exception):
    """The input is not a save this tool can read."""


# ---------------------------------------------------------------------------------------------------------------
# The parts of the game this depends on
# ---------------------------------------------------------------------------------------------------------------

M32 = 0xFFFFFFFF


def f32(x):
    """Round to a 32-bit float, as the game's float arithmetic does."""
    return struct.unpack("<f", struct.pack("<f", x))[0]


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


UNIX_EPOCH_SECONDS = 62135596800       # seconds from 0001-01-01 (DateTime tick 0) to 1970-01-01
TICKS_PER_SECOND = 10_000_000


def parse_tz(text):
    """A time zone from --tz: None or "local" (this machine's), "UTC", an IANA name ("Europe/Prague") or a fixed
    offset ("+02:00", "-0430"). Returns a tzinfo, or None for this machine's own zone."""
    if text is None or text.lower() == "local":
        return None
    t = text.strip()
    if t.upper() in ("UTC", "Z", "GMT"):
        return datetime.timezone.utc
    if t[:1] in "+-" and t[1:].replace(":", "").isdigit():
        digits = t[1:].replace(":", "")
        if len(digits) <= 2:
            digits = digits.zfill(2) + "00"
        if len(digits) != 4 or int(digits[2:]) >= 60 or int(digits[:2]) > 14:
            raise SaveError(f"{text!r} is not a time zone offset like +02:00")
        minutes = int(digits[:2]) * 60 + int(digits[2:])
        return datetime.timezone(datetime.timedelta(minutes=-minutes if t[0] == "-" else minutes))
    try:
        import zoneinfo
        return zoneinfo.ZoneInfo(t)
    except Exception:
        raise SaveError(f"unknown time zone {text!r}: use an IANA name such as Europe/Prague, UTC or an offset "
                        "such as +02:00")


def tz_label(tz, at=None):
    """The zone's name, plus the UTC offset in force at Unix second `at` when given."""
    name = "this machine's time zone" if tz is None else str(getattr(tz, "key", None) or tz)
    if at is None or isinstance(tz, datetime.timezone):
        return name
    off = tz_offset_seconds(at, tz)
    return f"{name}, UTC{'+' if off >= 0 else '-'}{abs(off) // 3600:02d}:{abs(off) % 3600 // 60:02d}"


def local_wall(created, tz):
    """The local date and time the game holds for a creation stamp (Unix seconds, UTC), as Valheim 1.0.30 loads it:
    DateTimeOffset.FromUnixTimeSeconds(created).LocalDateTime, with the offset in force at that instant."""
    utc = datetime.datetime.fromtimestamp(created, datetime.timezone.utc)
    local = utc.astimezone() if tz is None else utc.astimezone(tz)
    return local.replace(tzinfo=None)


def wall_ticks(wall):
    """DateTime.Ticks of a naive local date and time (whole seconds; the save keeps nothing finer)."""
    delta = wall.replace(microsecond=0) - datetime.datetime(1, 1, 1)
    return (delta.days * 86400 + delta.seconds) * TICKS_PER_SECOND


def ticks_hash(ticks):
    """DateTime.GetHashCode() as in the game's mscorlib: (int)ticks ^ (int)(ticks >> 32)."""
    return s32((ticks & M32) ^ ((ticks >> 32) & M32))


def date_base(created, tz):
    """The part of every default seed that comes from the character: m_dateCreated.GetHashCode()."""
    return ticks_hash(wall_ticks(local_wall(created, tz)))


def parse_created(text, tz):
    """--created: the in-game "Created:" date and time (local, "YYYY-MM-DD HH:MM:SS"), or "@" + Unix seconds as the
    save stores it. Returns (Unix seconds or None, naive local datetime)."""
    t = text.strip()
    if t.startswith("@") and t[1:].lstrip("-").isdigit():
        created = int(t[1:])
        return created, local_wall(created, tz)
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
        try:
            return None, datetime.datetime.strptime(t, fmt)
        except ValueError:
            pass
    raise SaveError(f"cannot read the creation date {text!r}: use \"YYYY-MM-DD HH:MM:SS\" (the in-game local time) or "
                    "@<unix seconds>")


VALUE_SCALE = struct.unpack("<f", bytes.fromhex("01000034"))[0]     # the constant UnityPlayer.so multiplies by


class UnityRandom:
    """UnityEngine.Random after InitState(seed), as implemented in UnityPlayer.so."""

    def __init__(self, seed):
        s0 = seed & M32
        s1 = (s0 * 0x6C078965 + 1) & M32
        s2 = (s1 * 0x6C078965 + 1) & M32
        s3 = (s2 * 0x6C078965 + 1) & M32
        self.s = [s0, s1, s2, s3]

    def _next(self):
        s0, s1, s2, s3 = self.s
        t = (s0 ^ (s0 << 11)) & M32
        new = (t ^ s3 ^ (t >> 8) ^ (s3 >> 19)) & M32
        self.s = [s1, s2, s3, new]
        return new

    def value(self):
        """Random.value, a float in [0, 1]."""
        return f32(f32(self._next() & 0x7FFFFF) * VALUE_SCALE)

    def range(self, low, high):
        """Random.Range(int, int)."""
        return low + self._next() % (high - low)


def roll(seed):
    """What GetItemUpgradeChance does with a seed: (the roll, the seed it stores afterwards)."""
    rng = UnityRandom(seed)
    return rng.value(), rng.range(0, 99999999)


# ---------------------------------------------------------------------------------------------------------------
# Reading the save
# ---------------------------------------------------------------------------------------------------------------

class Reader:
    def __init__(self, data, pos=0):
        self.d, self.p = data, pos

    def take(self, fmt):
        v = struct.unpack_from("<" + fmt, self.d, self.p)[0]
        self.p += struct.calcsize("<" + fmt)
        return v

    def skip(self, n):
        if n < 0 or self.p + n > len(self.d):
            raise SaveError("unexpected end of the save")
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

    def num_items(self):
        n = self.take("B")
        return ((n & 0x7F) << 8) | self.take("B") if n & 0x80 else n

    def skip_dict(self):
        for _ in range(self.take("i")):
            self.string()
            self.skip(4)


def read_item(r):
    """One ItemDrop.ItemData as saved (item version 110)."""
    r.skip(4)                                   # durability * 100
    r.skip(3)                                   # grid x, grid y, world level
    flags = r.take("B")
    quality = r.take("H") if flags & 4 else 1
    stack = r.take("H") if flags & 8 else 1
    if flags & 16:
        r.skip(4)                               # variant
    if flags & 32:
        r.skip(8)                               # crafter id
        r.string()                              # crafter name
    prefab = r.take("i") if flags & 64 else 0
    if flags & 128:
        for _ in range(r.num_items()):
            r.string()
            r.string()
    r.skip(1)                                   # cheated flag
    return {"prefab": prefab, "quality": quality, "stack": stack, "equipped": bool(flags & 2)}


def read_header(r):
    """Read a save's profile up to and including the creation date: (name, created as Unix seconds, UTC)."""
    version = r.take("i")
    if not PROFILE_MIN_VERSION <= version <= 1000:
        raise SaveError("this is not a supported Valheim .fch character file")
    if (r.take("i"), r.take("i")) != (STAT_COUNT, SET_COUNT):
        raise SaveError("the game's save layout changed and the script needs updating")
    for _ in range(SET_COUNT):
        r.skip(4 * STAT_COUNT)
        for _ in range(3):
            r.skip_dict()
        for _ in range(r.take("i")):
            r.skip_dict()
        for _ in range(5):                  # picked up, crafted, pickables, foods eaten, pieces built
            r.skip_dict()
    r.skip(1)                               # first spawn
    for _ in range(r.take("i")):            # per-world data
        r.skip(8 + 1 + 12 + 1 + 12 + 1 + 12 + 12)
        if r.take("?"):
            r.skip(r.take("i"))             # map
    name = r.string()
    r.skip(8)                               # player id
    r.string()                              # start seed
    r.skip(1)                               # used cheats
    created = r.take("q")                   # date created: Unix seconds (UTC)
    return name, created


def read_created(source):
    """Only the character name and creation date of a save (a path or bytes): enough for a character that was just
    created, and independent of the rest of the file's layout. Returns (name, Unix seconds, UTC)."""
    raw = bytes(source) if isinstance(source, (bytes, bytearray)) else open(source, "rb").read()
    try:
        return read_header(Reader(raw[4:4 + struct.unpack_from("<i", raw, 0)[0]]))
    except SaveError:
        raise
    except (struct.error, IndexError, UnicodeDecodeError, OverflowError):
        raise SaveError("this is not a supported Valheim .fch character file")


def load(source):
    """The character name, the inventory and the stored upgrade seeds of a save (a path or bytes)."""
    raw = bytes(source) if isinstance(source, (bytes, bytearray)) else open(source, "rb").read()
    try:
        data = raw[4:4 + struct.unpack_from("<i", raw, 0)[0]]
        r = Reader(data)
        name, created = read_header(r)
        if not r.take("?"):
            raise SaveError("this character has no player data yet")
        blob_len = r.take("i")
        blob_end = r.p + blob_len
        if blob_end != len(data):
            raise SaveError("the player data does not end where the file does")
        player_version = r.take("i")
        if player_version < PLAYER_DATA_VERSION:
            # version 34 added the per-character upgrade seeds, which made the Forge of Potential's rolls predictable
            raise SaveError(f"this character was saved by an older Valheim version (player data version {player_version}). "
                            "The Forge of Potential existed before, but its upgrade rolls changed in the latest update, and "
                            "only since then are they decided by the character and stored in its file. Load the character "
                            "in the current Valheim (1.0.20 or newer) and save it there first. Until then there is nothing "
                            "to predict")
        if player_version != PLAYER_DATA_VERSION:
            raise SaveError("the player data format changed and the script needs updating")
        r.skip(16)                              # max health, health, max stamina, time since death
        r.string()                              # guardian power
        r.skip(4)                               # guardian power cooldown
        r.skip(4)                               # inventory version
        items = [read_item(r) for _ in range(r.take("H"))]
        for _ in range(r.take("i")):            # known recipes
            r.string()
        for _ in range(r.take("i")):            # known stations
            r.string()
            r.skip(4)
        for _ in range(4):                      # materials, tutorials, uniques, trophies
            for _ in range(r.take("i")):
                r.string()
        for _ in range(r.take("i")):            # known biomes
            r.string()
        for _ in range(r.take("i")):            # known texts
            r.string()
            r.string()
        r.string()                              # beard
        r.string()                              # hair
        r.skip(12 + 12 + 4)                     # skin colour, hair colour, model index
        for _ in range(r.take("i")):            # food
            r.string()
            r.skip(4)
        r.skip(4)                               # skills version
        r.skip(r.take("i") * 12)                # skills
        for _ in range(r.take("i")):            # custom data
            r.string()
            r.string()
        r.skip(12)                              # stamina, max eitr, eitr
        r.skip(r.take("i"))                     # build menu state
        r.skip(r.take("i") * 8)                 # pseudo counters
        seeds = {}
        for _ in range(r.take("i")):
            key = r.take("i")
            seeds[key] = r.take("i")
        if r.p != blob_end:
            raise SaveError("the player data has an unexpected layout and the script needs updating")
    except SaveError:
        raise
    except (struct.error, IndexError, UnicodeDecodeError, OverflowError):
        raise SaveError("this is not a supported Valheim .fch character file, or its layout changed and the script "
                        "needs updating")
    return {"name": name, "created": created, "items": items, "seeds": seeds}


# ---------------------------------------------------------------------------------------------------------------
# The prediction
# ---------------------------------------------------------------------------------------------------------------

def predict(prefab, quality, base, seeds, update=False):
    """Replay upgrade attempts on an item until it breaks. Returns a dict describing the run.

    `base` is what the character adds to a key for a default seed: date_base() of its creation date (Valheim 1.0.30
    and newer), or stable_hash() of its name (1.0.20 to 1.0.29).

    The replay updates the seeds as the game would. They are copied first, unless `update` is true: then the dict that
    was passed in is changed, so the next copy of the item continues from the seeds this one left behind."""
    if not update:
        seeds = dict(seeds)
    item_hash = stable_hash(prefab)
    level, steps = quality, []
    for _ in range(MAX_ATTEMPTS):
        target = level + 1
        key = s32(item_hash + target)
        saved = key in seeds
        seed = seeds[key] if saved else s32(base + key)
        value, seeds[key] = roll(seed)
        if UPGRADE_CHANCE >= value:
            outcome, level = "success", target
        elif BREAK_CHANCE >= f32(1.0 - value):
            outcome = "broke"
        else:
            outcome, level = "failed", target - 2
        steps.append({"to": target, "roll": round(value, 4), "outcome": outcome, "savedSeed": saved})
        if outcome == "broke":
            break
    broke = steps[-1]["outcome"] == "broke"
    return {"item": prefab, "from": quality, "broke": broke, "attempts": len(steps),
            "upgrades": sum(1 for s in steps if s["outcome"] == "success"),
            "breaksAt": steps[-1]["to"] if broke else None, "steps": steps}


def fast_roll(seed):
    """(Random.value after InitState(seed), the seed the game stores afterwards): roll() without the generator object."""
    s0 = seed & M32
    s1 = (s0 * 0x6C078965 + 1) & M32
    s2 = (s1 * 0x6C078965 + 1) & M32
    s3 = (s2 * 0x6C078965 + 1) & M32
    t = (s0 ^ (s0 << 11)) & M32
    first = (t ^ s3 ^ (t >> 8) ^ (s3 >> 19)) & M32
    t = (s1 ^ (s1 << 11)) & M32
    second = (t ^ first ^ (t >> 8) ^ (first >> 19)) & M32
    return f32(f32(first & 0x7FFFFF) * VALUE_SCALE), second % 99999999


def matches(h, keys, target, copies):
    """Does a new character whose creation time hashes to h get the wanted result?

    One copy: exactly `target` upgrades, then a break. Several copies, upgraded one after another with the seeds the
    previous ones left behind: every copy but the last gets exactly `target` upgrades and breaks, and the last one
    succeeds at the level where the others broke."""
    seeds = [(h + k) & M32 for k in keys]          # the seed each level's key starts from
    for copy in range(copies):
        for i in range(target + 1):
            value, seeds[i] = fast_roll(seeds[i])
            succeeds = value <= UPGRADE_CHANCE
            if i < target or (copies > 1 and copy == copies - 1):
                if not succeeds:
                    return False
            elif succeeds or BREAK_CHANCE < f32(1.0 - value):
                return False
    return True


def reaches(h, first_key, target, copies):
    """The relay planner's rule (with one copy): the character gets at least `target` upgrades in a row. With more copies,
    copies 1 to N-1 are upgraded one after another until each breaks, and the last copy then gets `target` upgrades. All copies start at the same level, and `first_key` is
    the key of the first level they go to. Returns True when a character whose creation time hashes to h manages that."""
    seeds = {}                                      # level index -> the seed its next attempt starts from
    for copy in range(copies):
        kept = copy == copies - 1
        level = 0
        while level < MAX_ATTEMPTS:
            seed = seeds[level] if level in seeds else (h + first_key + level) & M32
            value, seeds[level] = fast_roll(seed)
            if value <= UPGRADE_CHANCE:
                level += 1
                if kept and level >= target:
                    return True
            elif BREAK_CHANCE >= f32(1.0 - value):
                break                               # this copy broke
            else:
                return False                        # a failed attempt lowers the level; not modelled
        if kept:
            return False
    return False


def wall_seconds(wall):
    """Whole seconds from 0001-01-01 to a naive local date and time."""
    return wall_ticks(wall) // TICKS_PER_SECOND


def from_wall_seconds(sec):
    return datetime.datetime(1, 1, 1) + datetime.timedelta(seconds=sec)


def wall_instant(wall, tz):
    """Unix seconds of a naive local date and time in tz (None: this machine's zone)."""
    return int(wall.timestamp() if tz is None else wall.replace(tzinfo=tz).timestamp())


def wall_exists(wall, tz):
    """Does this local date and time ever show on a clock in tz? Not when summer time skips it (the clock jumps from
    02:00 to 03:00, say), so a character can never be created at it there."""
    return local_wall(wall_instant(wall, tz), tz) == wall


def find_times(prefab, quality, target, start, limit, max_tries, copies=1, reach=False, tz=False):
    """Creation times, from `start` (a naive local date and time) on, at which a new character's `prefab`, starting at
    `quality`, gets exactly `target` upgrades and then breaks (see matches() for copies; with reach=True the rule of
    reaches() is used instead).

    A new character's default seeds come from the local date and time it was created at, to the second, as the clock of
    the computer running the game showed it. The save stores that moment in UTC and the game turns it back into the
    same local time, so the time zone does not change the rolls: only the wall-clock second does. It decides which
    seconds exist, though: with `tz` (None for this machine's zone, False to skip the check), times that the clock
    skips there (the start of summer time) are left out.
    Returns (naive datetimes, number of seconds tried)."""
    item_hash = stable_hash(prefab)
    keys = [(item_hash + quality + 1 + i) & M32 for i in range(target + 1)]
    first = wall_seconds(start)
    found = []
    for i in range(max_tries):
        sec = first + i
        h = ticks_hash(sec * TICKS_PER_SECOND)
        if reaches(h, keys[0], target, copies) if reach else matches(h, keys, target, copies):
            wall = from_wall_seconds(sec)
            if tz is not False and not wall_exists(wall, tz):
                continue
            found.append(wall)
            if len(found) >= limit:
                return found, i + 1
    return found, max_tries


def fmt_wall(wall):
    return wall.strftime("%Y-%m-%d %H:%M:%S")


def find_item(text):
    """A prefab name from a prefab name or a display name (case does not matter)."""
    low = text.lower()
    for prefab, shown in UPGRADABLE.items():
        if low in (prefab.lower(), shown.lower()):
            return prefab
    matches = [p for p, shown in UPGRADABLE.items() if low in shown.lower() or low in p.lower()]
    if len(matches) == 1:
        return matches[0]
    raise SaveError(f"{text!r} is not an upgradable item" if not matches else
                    f"{text!r} matches several items: " + ", ".join(sorted(matches)[:12]))


def run(save, base, item=None, quality=1, every=False):
    """Predictions for the chosen items, as a list of dicts. `base`: see predict()."""
    out = []
    if item:
        prefab = find_item(item)
        out.append({**predict(prefab, quality, base, save["seeds"]), "name": UPGRADABLE[prefab], "stack": 1})
    elif every:
        for prefab in UPGRADABLE:
            out.append({**predict(prefab, 1, base, save["seeds"]), "name": UPGRADABLE[prefab], "stack": 1})
    else:
        by_hash = {stable_hash(p): p for p in UPGRADABLE}
        for it in save["items"]:
            prefab = by_hash.get(it["prefab"])
            if prefab:
                out.append({**predict(prefab, it["quality"], base, save["seeds"]), "name": UPGRADABLE[prefab],
                            "stack": it["stack"], "equipped": it["equipped"]})
    return out


def check(save, base, deepest=25):
    """Compare each saved seed with the seed the generator predicts for it (the seed stored after a first attempt)."""
    by_key = {}
    for prefab, shown in UPGRADABLE.items():
        for level in range(2, 40):
            by_key[s32(stable_hash(prefab) + level)] = (prefab, shown, level)
    rows = []
    for key, stored in sorted(save["seeds"].items()):
        known = by_key.get(key)
        if not known:
            rows.append({"key": key, "item": None, "attempts": None})
            continue
        rule, attempts = None, None
        for name, b in (("date", base), ("name", stable_hash(save["name"]) if save.get("name") else None)):
            if b is None:
                continue
            seed = s32(b + key)
            for n in range(1, deepest + 1):
                seed = roll(seed)[1]
                if seed == stored:
                    rule, attempts = name, n
                    break
            if attempts:
                break
        rows.append({"key": key, "item": known[1], "level": known[2], "attempts": attempts, "rule": rule})
    return rows


# ---------------------------------------------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------------------------------------------

def describe(p):
    if p["broke"]:
        return f"{p['upgrades']} upgrade{'s' if p['upgrades'] != 1 else ''}, then it breaks going to level {p['breaksAt']}"
    return f"survives {MAX_ATTEMPTS} attempts"


def show(results, verbose):
    if not results:
        print("No upgradable items in the inventory. Use --item NAME to try a fresh one, or --all.")
        return
    results = sorted(results, key=lambda p: (-p["upgrades"], p["name"].lower()))
    width = max(len(p["name"]) for p in results)
    for p in results:
        stack = f" x{p['stack']}" if p.get("stack", 1) > 1 else ""
        print(f"{p['name'] + stack:<{width + 5}} level {p['from']}:  {describe(p)}")
        if verbose:
            for s in p["steps"]:
                src = "saved seed" if s["savedSeed"] else "default seed"
                print(f"    to level {s['to']}: roll {s['roll']:.4f} -> {s['outcome']}  ({src})")


def show_check(rows):
    if not rows:
        print("This character has no saved upgrade seeds yet: no upgrade has been attempted at the Forge of Potential.")
        return
    ok = sum(1 for r in rows if r["rule"] == "date")
    old = sum(1 for r in rows if r["rule"] == "name")
    for r in rows:
        if r["item"] is None:
            print(f"key {r['key']}: not one of the known upgradable items")
        elif r["attempts"]:
            how = "" if r["rule"] == "date" else " (from the character name: made before Valheim 1.0.30)"
            print(f"{r['item']} to level {r['level']}: seed matches after {r['attempts']} attempt(s){how}")
        else:
            print(f"{r['item']} to level {r['level']}: seed does NOT match the generator (wrong --tz or --created?)")
    print(f"{ok} of {len(rows)} saved seeds reproduced from the creation date"
          + (f", {old} more from the character name (made before 1.0.30)" if old else ""))


# ---------------------------------------------------------------------------------------------------------------
# Entry points for the web page (web/finder-worker.js runs this file in the browser with Pyodide)
# ---------------------------------------------------------------------------------------------------------------

# The game saves an item's quality as an unsigned 16-bit number, so this is the highest quality an item can have.
WEB_MAX_QUALITY = 65535
# The most seconds one web search tries (about 93 days of creation times).
WEB_MAX_SECONDS = 8_000_000


def web_items():
    """JSON list of the display names of every upgradable item."""
    return json.dumps(sorted(UPGRADABLE.values(), key=str.lower))


def start_wall(text, zone=None):
    """A search start from the page: a local date and time ("YYYY-MM-DDTHH:MM[:SS]"), or now in `zone`."""
    if text:
        return parse_created(text, zone)[1]
    return local_wall(int(datetime.datetime.now().timestamp()), zone)


def not_before_now(wall, zone):
    """`wall`, or the next second in `zone` when `wall` has already gone: the page never lists a time that has passed."""
    soon = local_wall(int(datetime.datetime.now().timestamp()) + 1, zone)
    return max(wall, soon)


def web_zone(tz):
    """The time zone a page field names ("" or None: the browser's own, which Pyodide's localtime follows)."""
    return parse_tz(tz or None)


def web_zone_label(zone, at=None):
    return tz_label(zone, at).replace("this machine's", "your browser's")


def checked_wall(text, zone):
    """A local date and time typed on the page, which must exist on a clock in `zone`."""
    wall = parse_created(text, zone)[1]
    if not wall_exists(wall, zone):
        raise SaveError(f"{fmt_wall(wall)} never shows on a clock in {web_zone_label(zone)}: summer time skips it")
    return wall


def web_find(item, quality, limit, after="", start="", upgrades=MAX_FIRST_RUN, tz=""):
    """JSON for the time finder: creation times (local, from `start` on) at which a new character gets exactly
    `upgrades` upgrades (then a break) on `item` starting at `quality`. `after` is the last time of an earlier answer;
    the search continues from the second after it. `tz` is the time zone of the computer running the game: the times
    are local times there, and seconds its clock skips are left out."""
    try:
        quality, limit, upgrades = int(quality), int(limit), int(upgrades)
        if not 1 <= quality <= WEB_MAX_QUALITY:
            raise SaveError(f"the starting quality must be between 1 and {WEB_MAX_QUALITY}")
        if not 1 <= upgrades <= MAX_FIRST_RUN:
            raise SaveError(f"the upgrades in a row must be between 1 and {MAX_FIRST_RUN}")
        prefab = find_item(item)
        zone = web_zone(tz)
        begin = (parse_created(after, zone)[1] + datetime.timedelta(seconds=1)) if after else start_wall(start, zone)
        begin = not_before_now(begin, zone)
        times, tried = find_times(prefab, quality, upgrades, begin, max(1, min(limit, 100)), WEB_MAX_SECONDS, tz=zone)
    except (SaveError, ValueError) as e:
        return json.dumps({"error": str(e)})
    return json.dumps({"item": UPGRADABLE[prefab], "from": quality, "upgrades": upgrades,
                       "times": [fmt_wall(t) for t in times], "start": fmt_wall(begin), "tried": tried,
                       "end": fmt_wall(begin + datetime.timedelta(seconds=tried - 1)), "timeZone": web_zone_label(zone)})


def web_predict(data, tz=None):
    """JSON for the web page's save predictor: what happens to every upgradable item in the character's inventory.

    `data` is the file's bytes (a Uint8Array from the page, or bytes). The default seeds come from the creation date in
    the file, read in time zone `tz` (see parse_tz; by default the browser's own zone, which Pyodide's localtime uses)."""
    try:
        raw = bytes(data.to_py()) if hasattr(data, "to_py") else bytes(data)
        save = load(raw)
        zone = web_zone(tz)
        items = run(save, date_base(save["created"], zone))
    except SaveError as e:
        return json.dumps({"error": str(e)})
    items.sort(key=lambda p: (-p["upgrades"], p["name"].lower()))
    return json.dumps({"character": save["name"], "savedSeeds": len(save["seeds"]), "items": items,
                       "created": local_wall(save["created"], zone).strftime("%Y-%m-%d %H:%M:%S"),
                       "timeZone": web_zone_label(zone, save["created"])})


def web_created(data, tz=""):
    """JSON for the timer's check: the name and creation time of a dropped save, as Unix seconds and as the local time
    in time zone `tz` (default: the browser's)."""
    try:
        raw = bytes(data.to_py()) if hasattr(data, "to_py") else bytes(data)
        name, created = read_created(raw)
        zone = web_zone(tz)
    except SaveError as e:
        return json.dumps({"error": str(e)})
    return json.dumps({"character": name, "createdUnix": created, "created": fmt_wall(local_wall(created, zone)),
                       "timeZone": web_zone_label(zone, created)})


def web_predict_item(item, quality, created, tz=""):
    """JSON for the predictor's manual form: one item at a quality, for a new character (no saved seeds) created at the
    local date and time `created` ("YYYY-MM-DDTHH:MM[:SS]") in time zone `tz` (default: the browser's)."""
    try:
        quality = int(quality)
        if not 1 <= quality <= WEB_MAX_QUALITY:
            raise SaveError(f"the quality must be between 1 and {WEB_MAX_QUALITY}")
        if not created:
            raise SaveError("enter the character's creation date and time")
        zone = web_zone(tz)
        wall = checked_wall(created, zone)
        prefab = find_item(item)
    except (SaveError, ValueError) as e:
        return json.dumps({"error": str(e)})
    return json.dumps({"created": fmt_wall(wall), "timeZone": web_zone_label(zone, wall_instant(wall, zone)),
                       "item": {**predict(prefab, quality, ticks_hash(wall_ticks(wall)), {}), "name": UPGRADABLE[prefab],
                                "stack": 1}})


def relay_plan(prefab, start, target, begin, per=MAX_FIRST_RUN, gap=60, max_tries=WEB_MAX_SECONDS, tz=False):
    """A chain of new characters that takes the item from `start` to `target` without breaking it.

    Each character makes only upgrades its own rolls get right: the first character takes `per` levels (at most
    MAX_FIRST_RUN), hands the item over, and the next one continues from there. Every character is new, so its rolls
    start from its creation time; the times are found one after another from `begin` (a naive local date and time),
    each at least `gap` seconds after the one before, to leave time to create the characters. Returns a list of {"created", "from", "to", "steps"}; raises SaveError when a part of the chain cannot be
    found within max_tries seconds."""
    plan, level, at = [], start, begin
    while level < target:
        need = min(per, target - level)
        times, tried = find_times(prefab, level, need, at, 1, max_tries, reach=True, tz=tz)
        if not times:
            raise SaveError(f"no creation time found for the upgrades from quality {level} within {max_tries:,} seconds "
                            f"from {fmt_wall(at)}")
        when = times[0]
        steps = predict(prefab, level, ticks_hash(wall_ticks(when)), {})["steps"][:need]
        plan.append({"created": fmt_wall(when), "from": level, "to": level + need, "steps": steps})
        level += need
        at = when + datetime.timedelta(seconds=gap)
    return plan


def web_relay(item, start, target, begin="", per=4, tz=""):
    """JSON for the relay planner. `begin`: the local date and time to search from (default: now); `per`: the levels
    each character takes (fewer means more characters, but times much closer together); `tz`: the time zone of the
    computer running the game (default: the browser's)."""
    try:
        start, target, per = int(start), int(target), int(per)
        if not 1 <= per <= MAX_FIRST_RUN:
            raise SaveError(f"the levels per character must be between 1 and {MAX_FIRST_RUN}")
        if not 1 <= start <= WEB_MAX_QUALITY or not 1 <= target <= WEB_MAX_QUALITY:
            raise SaveError(f"the qualities must be between 1 and {WEB_MAX_QUALITY}")
        if target <= start:
            raise SaveError("the target quality must be higher than the current quality")
        prefab = find_item(item)
        zone = web_zone(tz)
        plan = relay_plan(prefab, start, target, not_before_now(start_wall(begin, zone), zone), per, tz=zone)
    except (SaveError, ValueError) as e:
        return json.dumps({"error": str(e)})
    return json.dumps({"item": UPGRADABLE[prefab], "from": start, "to": target, "per": per, "plan": plan,
                       "timeZone": web_zone_label(zone)})


def tz_offset_seconds(t, tz):
    """The UTC offset (seconds) in force at Unix second t in tz (None: this machine's zone)."""
    dt = datetime.datetime.fromtimestamp(t, datetime.timezone.utc)
    off = (dt.astimezone() if tz is None else dt.astimezone(tz)).utcoffset()
    return int(off.total_seconds())


def find_times_command(ap, args, tz):
    """--findtime: needs no save, only the item, its starting level and where to start looking."""
    if args.save:
        ap.error("--findtime works without a save file: a new character has no saved seeds. Drop the save path")
    if not args.item:
        ap.error("--findtime needs a specific item: add --item NAME")
    if args.quality is None:
        ap.error("--findtime needs the level the item starts at: add --quality N (use 1 for a fresh item)")
    if args.check or args.all:
        ap.error("--findtime cannot be combined with --check or --all")
    if not 1 <= args.copies <= 5:
        ap.error("--copies must be between 1 and 5")
    if args.quality < 1 or args.findtime < 0:
        ap.error("need --quality >= 1 and N >= 0")
    if args.findtime > MAX_FIRST_RUN:
        ap.error(f"no character can get more than {MAX_FIRST_RUN} upgrades before the first break: the first rolls "
                 "of consecutive levels are correlated (all 2^32 starting seeds were checked)")
    try:
        prefab = find_item(args.item)
        if args.created:
            start = parse_created(args.created, tz)[1]
        else:
            start = (datetime.datetime.now() if tz is None else datetime.datetime.now(tz)).replace(tzinfo=None, microsecond=0)
    except SaveError as e:
        ap.error(str(e))
    maxtries = args.maxtries or (31 * 86400 if args.copies == 1 else 366 * 86400)
    times, tried = find_times(prefab, args.quality, args.findtime, start, args.limit, maxtries, args.copies, tz=tz)
    hits = []
    for t in times:
        shared = {}                                 # the seeds the copies leave behind for each other
        base = ticks_hash(wall_ticks(t))
        runs = [predict(prefab, args.quality, base, shared, update=True) for _ in range(args.copies)]
        hits.append({**runs[0], "name": UPGRADABLE[prefab], "createdLocal": fmt_wall(t), "copies": runs})
    if args.json:
        print(json.dumps({"item": prefab, "from": args.quality, "upgrades": args.findtime, "copies": args.copies,
                          "start": fmt_wall(start), "tried": tried, "times": hits}, indent=1))
        return
    if args.copies == 1:
        more = ""
    elif args.copies == 2:
        more = ", then a second copy reaching the level where the first one broke"
    else:
        more = f", the same for copies 2 to {args.copies - 1}, and copy {args.copies} getting past that level"
    print(f"{UPGRADABLE[prefab]} from level {args.quality}: character creation times where copy 1 gets exactly "
          f"{args.findtime} upgrade{'s' if args.findtime != 1 else ''} and breaks{more}")
    print(f"(the local time on the clock of the computer running the game; {tried:,} seconds searched from "
          f"{fmt_wall(start)})")
    for h in hits:
        runs = h["copies"]
        for i, r in enumerate(runs):
            last = args.copies > 1 and i == args.copies - 1
            assert r["upgrades"] >= args.findtime + (1 if last else 0) and (last or r["broke"]), "time check failed"
        print(f"  {h['createdLocal']}" + ("" if args.copies == 1 else
              "   (" + "; ".join(f"copy {i + 1}: {r['upgrades']} upgrades" + (f", breaks going to {r['breaksAt']}" if r["broke"] else "")
                                  for i, r in enumerate(runs)) + ")"))
        if args.verbose:
            for i, r in enumerate(runs):
                if args.copies > 1:
                    print(f"      copy {i + 1}:")
                for st in r["steps"]:
                    print(f"      to level {st['to']}: roll {st['roll']:.4f} -> {st['outcome']}")
    if not hits:
        print("  none found yet; raise --maxtries")


def main():
    ap = argparse.ArgumentParser(
        description="Predict how many upgrades an item can take at the Forge of Potential before it breaks "
                    "(Valheim 1.0.30 and newer: first rolls come from the character's creation date and time zone).")
    ap.add_argument("save", nargs="?", help="path to the .fch character file (optional with --created, not used with "
                    "--findtime)")
    ap.add_argument("--tz", help="time zone of the machine that runs the game: an IANA name (Europe/Prague), UTC or an "
                    "offset (+02:00). The game turns the saved UTC creation stamp into local time with it, so it changes "
                    "every first roll (default: this machine's zone)")
    ap.add_argument("--created", help="the character's creation date and time instead of the one in the save: the "
                    "in-game local time as \"YYYY-MM-DD HH:MM:SS\" (shown as Created: in the game's texts), or @<unix "
                    "seconds> as the save stores it. Without a save: predict for a new character (no saved seeds). With "
                    "--findtime: where the search starts (default: now)")
    ap.add_argument("--item", help="a prefab name or display name (e.g. SwordIron or 'Iron Sword') instead of the inventory")
    ap.add_argument("--quality", type=int, help="level the --item starts at (default: 1; required with --findtime)")
    ap.add_argument("--all", action="store_true", help="every upgradable item, starting from level 1")
    ap.add_argument("-v", "--verbose", action="store_true", help="show every roll")
    ap.add_argument("--findtime", type=int, metavar="N",
                    help="search for character creation times (second by second, from --created or now) at which a new "
                    "character's --item, starting at --quality, gets exactly N upgrades before it breaks")
    ap.add_argument("--copies", type=int, default=1, metavar="N",
                    help="with --findtime: upgrade N copies of the item one after another with the same character. "
                    "The first N-1 get exactly the wanted upgrades and break; the last one gets past the level where they "
                    "broke (default: 1)")
    ap.add_argument("--limit", type=int, default=10, help="with --findtime: stop after this many times (default: 10)")
    ap.add_argument("--maxtries", type=int,
                    help="with --findtime: seconds to search (default: 31 days, or a year with --copies above 1)")
    ap.add_argument("--check", action="store_true", help="compare the saved seeds with the generator (a good test of "
                    "--tz: with the right zone, first-attempt seeds match)")
    ap.add_argument("--json", action="store_true", help="print the result as JSON")
    args = ap.parse_args()
    try:
        tz = parse_tz(args.tz)
    except SaveError as e:
        ap.error(str(e))
    if args.findtime is not None:
        find_times_command(ap, args, tz)
        return
    if not args.save and not args.created:
        ap.error("give the path to the .fch character file, or --created for a new character")
    quality = 1 if args.quality is None else args.quality
    try:
        if args.save:
            save = load(args.save)
        else:
            if not args.item and not args.all:
                ap.error("without a save there is no inventory: add --item NAME or --all")
            if args.check:
                ap.error("--check needs a save file")
            save = {"name": None, "created": None, "items": [], "seeds": {}}
        if args.created:
            created, wall = parse_created(args.created, tz)
        else:
            created, wall = save["created"], local_wall(save["created"], tz)
        base = ticks_hash(wall_ticks(wall))
        if args.check:
            rows = check(save, base)
            if args.json:
                print(json.dumps(rows, indent=1))
            else:
                show_check(rows)
            return
        results = run(save, base, args.item, quality, args.all)
    except FileNotFoundError:
        ap.error(f"file not found: {args.save}")
    except OSError as e:
        ap.error(f"cannot read {args.save}: {e.strerror or e}")
    except SaveError as e:
        ap.error(f"{args.save}: {e}" if args.save else str(e))
    shown = wall.strftime("%Y-%m-%d %H:%M:%S")
    zone = "as given" if created is None else tz_label(tz, created)
    if args.json:
        print(json.dumps({"character": save["name"], "created": created, "createdLocal": shown, "timeZone": zone,
                          "seedBase": base, "savedSeeds": len(save["seeds"]), "items": results}, indent=1))
        return
    who = save["name"] or "A new character"
    print(f"{who}: created {shown} local time ({zone}), {len(save['seeds'])} saved upgrade seed(s)")
    show(results, args.verbose)


if __name__ == "__main__":
    main()
