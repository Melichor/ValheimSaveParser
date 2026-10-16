#!/usr/bin/env python3
"""upgrade_oracle: predict how many times an item can be upgraded at the upgrade station before it breaks.

Reads a Valheim character file (.fch, profile version 46 and up, player data version 34). Python 3, standard library only.

How the game decides an upgrade (Valheim, InventoryGui.DoCrafting and Player.GetItemUpgradeChance):
  * Each attempt is keyed by the item's prefab name hash plus the level it is being upgraded to.
  * The roll is Unity's Random.value after Random.InitState(seed). The seed is the one stored in the character for that
    key, or, when the key was never used, the hash of the character name plus the key.
  * After the roll the game stores a new random seed for the key, so the next attempt on the same key is a different roll.
  * The attempt succeeds when UPGRADE_CHANCE >= roll, destroys the item when BREAK_CHANCE >= 1 - roll, and otherwise
    lowers the item by one level.
The rolls therefore depend on nothing but the character name and the seeds saved in the file, which is what this script
replays. Unity's generator (a xorshift128 seeded as s[i] = s[i-1] * 1812433253 + 1) was taken from the game's UnityPlayer.so.

    python3 upgrade_oracle.py Character.fch                  # the upgradable items in the inventory
    python3 upgrade_oracle.py Character.fch --item SwordIron # a fresh item, or --quality N for one that is already upgraded
    python3 upgrade_oracle.py Character.fch --all            # every upgradable item from level 1
    python3 upgrade_oracle.py Character.fch --check          # compare the saved seeds with what the generator predicts
    python3 upgrade_oracle.py Character.fch --charname Ragnar # the same items for a fresh character with another name
    python3 upgrade_oracle.py --item SwordIron --quality 1 --findnameperupgr 6   # names that give exactly 6 upgrades (no save)
    python3 upgrade_oracle.py --item SwordIron --quality 4 --findnameperupgr 8 --copies 2   # ...and a second copy that gets past the break
"""
import argparse
import json
import struct
import sys
from itertools import islice, product

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
# Prefab name -> display name of every item that can be upgraded at the upgrade station.
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
    'ArmorDress1': 'Plain Brown Dress',
    'ArmorDress10': 'Simple Undyed Dress',
    'ArmorDress2': 'Brown Dress with Shawl',
    'ArmorDress3': 'Brown Dress with Beads',
    'ArmorDress4': 'Plain Blue Dress',
    'ArmorDress5': 'Blue Dress with Shawl',
    'ArmorDress6': 'Blue Dress with Beads',
    'ArmorDress7': 'Plain Yellow Dress',
    'ArmorDress8': 'Yellow Dress with Shawl',
    'ArmorDress9': 'Yellow Dress with Beads',
    'ArmorFenringChest': 'Fenris Coat',
    'ArmorFenringLegs': 'Fenris Leggings',
    'ArmorFlametalChest': 'Flametal Breastplate',
    'ArmorFlametalLegs': 'Flametal Greaves',
    'ArmorHarvester1': 'Harvest Tunic',
    'ArmorHarvester2': 'Harvest Dress',
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
    'ArmorTunic1': 'Plain Blue Tunic',
    'ArmorTunic10': 'Simple Undyed Tunic',
    'ArmorTunic2': 'Blue Tunic with Cape',
    'ArmorTunic3': 'Blue Tunic with Beads',
    'ArmorTunic4': 'Plain Red Tunic',
    'ArmorTunic5': 'Red Tunic with Cape',
    'ArmorTunic6': 'Red Tunic with Beads',
    'ArmorTunic7': 'Plain Yellow Tunic',
    'ArmorTunic8': 'Yellow Tunic with Cape',
    'ArmorTunic9': 'Yellow Tunic with Beads',
    'ArmorWolfChest': 'Wolf Hide Chestpiece',
    'ArmorWolfLegs': 'Wolf Hide Trousers',
    'AtgeirBlackmetal': 'Black Metal Atgeir',
    'AtgeirBronze': 'Bronze Atgeir',
    'AtgeirGold': 'Nord Atgeir',
    'AtgeirGold_BloodLightning': 'Thunderblood Atgeir',
    'AtgeirGold_FrostFire': 'Frostfire Atgeir',
    'AtgeirHimminAfl': 'Himminafl',
    'AtgeirIron': 'Iron Atgeir',
    'AtgeirWood': 'Wooden Atgeir',
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
    'AxeWood': 'Wooden Axe',
    'Battleaxe': 'Battleaxe',
    'BattleaxeBlackmetal': 'Black Metal Battleaxe',
    'BattleaxeCrystal': 'Crystal Battleaxe',
    'BattleaxeGold': 'Nord Greataxe',
    'BattleaxeGold_BloodLightning': 'Thunderblood Greataxe',
    'BattleaxeGold_FrostFire': 'Frostfire Greataxe',
    'BattleaxeSkullSplittur': 'Skull Splittur',
    'BattleaxeWood': 'Wooden Battleaxe',
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
    'Feaster': 'Serving Tray',
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
    'HelmetDNMage': 'Headdress of the Caller',
    'HelmetDNMediumHood': 'Hood of the Vanguard',
    'HelmetDrake': 'Drake Helmet',
    'HelmetFenring': 'Fenris Hood',
    'HelmetFishingHat': 'Fishing Hat',
    'HelmetFlametal': 'Flametal Helmet',
    'HelmetHat1': 'Blue Tied Headscarf',
    'HelmetHat10': 'Simple Purple Cap',
    'HelmetHat2': 'Green Twisted Headscarf',
    'HelmetHat3': 'Brown Fur Cap',
    'HelmetHat4': 'Extravagant Green Cap',
    'HelmetHat5': 'Simple Red Cap',
    'HelmetHat6': 'Yellow Tied Headscarf',
    'HelmetHat7': 'Red Twisted Headscarf',
    'HelmetHat8': 'Grey Fur Cap',
    'HelmetHat9': 'Extravagant Orange Cap',
    'HelmetIron': 'Iron Helmet',
    'HelmetLeather': 'Leather Helmet',
    'HelmetLox': 'Lox Fur Hood',
    'HelmetMage': 'Eitr-weave Hood',
    'HelmetMage_Ashlands': 'Hood of Embla',
    'HelmetOdin': 'Hood of Oden',
    'HelmetPadded': 'Padded Helmet',
    'HelmetPointyHat': 'Pointy Hat',
    'HelmetRoot': 'Root Mask',
    'HelmetStrawHat': 'Straw Hat',
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
    'KnifeVoid': 'Voidcaller',
    'KnifeWood': 'Wooden Knife',
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
    'MaceWood': 'Wooden Mace',
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
    'ShieldIronSquare': 'Iron Shield',
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
    'SledgeWood': 'Wooden Sledge',
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
    'SpearWood': 'Wooden Spear',
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
    'THSwordWood': 'Wooden Greatsword',
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


def load(source):
    """The character name, the inventory and the stored upgrade seeds of a save (a path or bytes)."""
    raw = bytes(source) if isinstance(source, (bytes, bytearray)) else open(source, "rb").read()
    try:
        data = raw[4:4 + struct.unpack_from("<i", raw, 0)[0]]
        r = Reader(data)
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
        r.skip(1 + 8)                           # used cheats, date created
        if not r.take("?"):
            raise SaveError("this character has no player data yet")
        blob_len = r.take("i")
        blob_end = r.p + blob_len
        if blob_end != len(data):
            raise SaveError("the player data does not end where the file does")
        if r.take("i") != PLAYER_DATA_VERSION:
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
    return {"name": name, "items": items, "seeds": seeds}


# ---------------------------------------------------------------------------------------------------------------
# The prediction
# ---------------------------------------------------------------------------------------------------------------

def predict(prefab, quality, name, seeds, update=False):
    """Replay upgrade attempts on an item until it breaks. Returns a dict describing the run.

    The replay updates the seeds as the game would. They are copied first, unless `update` is true: then the dict that
    was passed in is changed, so the next copy of the item continues from the seeds this one left behind."""
    if not update:
        seeds = dict(seeds)
    base = stable_hash(prefab)
    name_hash = stable_hash(name)
    level, steps = quality, []
    for _ in range(MAX_ATTEMPTS):
        target = level + 1
        key = s32(base + target)
        saved = key in seeds
        seed = seeds[key] if saved else s32(name_hash + key)
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


def first_value(seed):
    """Random.value after InitState(seed), the one roll a first attempt needs (a faster path for the name search)."""
    s0 = seed & M32
    s1 = (s0 * 0x6C078965 + 1) & M32
    s2 = (s1 * 0x6C078965 + 1) & M32
    s3 = (s2 * 0x6C078965 + 1) & M32
    t = (s0 ^ (s0 << 11)) & M32
    return f32(f32(((t ^ s3 ^ (t >> 8) ^ (s3 >> 19)) & M32) & 0x7FFFFF) * VALUE_SCALE)


CHARSETS = {
    "letters": "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz",
    "lower": "abcdefghijklmnopqrstuvwxyz",
    "alnum": "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789",
}


def hashed_names(charset, length):
    """Every name of that length in order, as (first part, last character, name hash mod 2^32).

    The hash runs two lanes, one over the even and one over the odd positions, so everything but the last character is
    hashed once per 52 names."""
    last_even = (length - 1) % 2 == 0
    for prefix in product(charset, repeat=length - 1):
        a = b = 5381
        for i, ch in enumerate(prefix):
            if i % 2 == 0:
                a = (((a << 5) + a) ^ ord(ch)) & M32
            else:
                b = (((b << 5) + b) ^ ord(ch)) & M32
        head = "".join(prefix)
        if last_even:
            a = ((a << 5) + a) & M32
            for ch in charset:
                yield head, ch, ((a ^ ord(ch)) + b * 1566083941) & M32
        else:
            b = ((b << 5) + b) & M32
            for ch in charset:
                yield head, ch, (a + (b ^ ord(ch)) * 1566083941) & M32


def matches(h, keys, target, copies):
    """Does a new character whose name hashes to h get the wanted result?

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
    """The advanced search's rule: copies 1 to N-1 are upgraded one after another until each breaks, and the last copy
    (the one that is kept) then gets `target` upgrades in a row. All copies start at the same level, and `first_key` is
    the key of the first level they go to. Returns True when a character whose name hashes to h manages that."""
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


def find_names(prefab, quality, target, charset, min_len, max_len, limit, max_tries, after=None, copies=1, reach=False):
    """Character names (shortest first) whose rolls give exactly `target` upgrades, then a break (see matches() for copies).

    A fresh character has no saved seeds, so each roll starts from the hash of the name plus the key of the level.
    `after` continues a search: it is the last name of the previous one, and the search resumes with the name after it.
    With reach=True the rule of reaches() is used instead.
    Returns (names, number of names tried, whether the search covered every name up to max_len)."""
    base = stable_hash(prefab)
    keys = [(base + quality + 1 + i) & M32 for i in range(target + 1)]
    first_key = keys[0]
    found, tried = [], 0
    for length in range(max(min_len, len(after or "")), max_len + 1):
        names = hashed_names(charset, length)
        if after and length == len(after):
            skip = 0
            for ch in after:
                skip = skip * len(charset) + charset.index(ch)
            names = islice(names, skip + 1, None)
        for head, last, h in names:
            tried += 1
            if tried > max_tries:
                return found, tried - 1, False
            if reaches(h, first_key, target, copies) if reach else matches(h, keys, target, copies):
                found.append(head + last)
                if len(found) >= limit:
                    return found, tried, False
    return found, tried, True


def upgrade_path(prefab, quality, name, copies, target):
    """What to do with each copy, for a name found by the advanced search: every copy but the last is upgraded until it
    breaks, the last one is upgraded `target` times and then left alone."""
    shared = {}                                     # the seeds the copies leave behind for each other
    path = []
    for i in range(copies):
        run = predict(prefab, quality, name, shared, update=True)
        kept = i == copies - 1
        steps = run["steps"][:target] if kept else run["steps"]
        path.append({"copy": i + 1, "role": "keep" if kept else "sacrifice", "from": quality,
                     "upgrades": sum(1 for st in steps if st["outcome"] == "success"),
                     "steps": steps, "breaksAt": None if kept else run["breaksAt"]})
    return path


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


def run(save, item=None, quality=1, every=False):
    """Predictions for the chosen items, as a list of dicts."""
    out = []
    if item:
        prefab = find_item(item)
        out.append({**predict(prefab, quality, save["name"], save["seeds"]), "name": UPGRADABLE[prefab], "stack": 1})
    elif every:
        for prefab in UPGRADABLE:
            out.append({**predict(prefab, 1, save["name"], save["seeds"]), "name": UPGRADABLE[prefab], "stack": 1})
    else:
        by_hash = {stable_hash(p): p for p in UPGRADABLE}
        for it in save["items"]:
            prefab = by_hash.get(it["prefab"])
            if prefab:
                out.append({**predict(prefab, it["quality"], save["name"], save["seeds"]), "name": UPGRADABLE[prefab],
                            "stack": it["stack"], "equipped": it["equipped"]})
    return out


def check(save, deepest=25):
    """Compare each saved seed with the seed the generator predicts for it (the seed stored after a first attempt)."""
    by_key = {}
    for prefab, shown in UPGRADABLE.items():
        for level in range(2, 40):
            by_key[s32(stable_hash(prefab) + level)] = (prefab, shown, level)
    name_hash = stable_hash(save["name"])
    rows = []
    for key, stored in sorted(save["seeds"].items()):
        known = by_key.get(key)
        if not known:
            rows.append({"key": key, "item": None, "attempts": None})
            continue
        seed, attempts = s32(name_hash + key), None
        for n in range(1, deepest + 1):
            seed = roll(seed)[1]
            if seed == stored:
                attempts = n
                break
        rows.append({"key": key, "item": known[1], "level": known[2], "attempts": attempts})
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
        print("This character has no saved upgrade seeds yet: no upgrade has been attempted at an upgrade station.")
        return
    ok = sum(1 for r in rows if r["attempts"])
    for r in rows:
        if r["item"] is None:
            print(f"key {r['key']}: not one of the known upgradable items")
        elif r["attempts"]:
            print(f"{r['item']} to level {r['level']}: seed matches after {r['attempts']} attempt(s)")
        else:
            print(f"{r['item']} to level {r['level']}: seed does NOT match the generator")
    print(f"{ok} of {len(rows)} saved seeds reproduced")


# ---------------------------------------------------------------------------------------------------------------
# Entry points for the web page (web/finder-worker.js runs this file in the browser with Pyodide)
# ---------------------------------------------------------------------------------------------------------------

WEB_MAX_QUALITY = 99


def web_items():
    """JSON list of the display names of every upgradable item."""
    return json.dumps(sorted(UPGRADABLE.values(), key=str.lower))


def web_find(item, quality, limit, after=""):
    """JSON for the name finder: character names that give MAX_FIRST_RUN upgrades on `item` starting at `quality`.

    `after` is the last name of an earlier answer; the search continues from there."""
    try:
        quality, limit = int(quality), int(limit)
        if not 1 <= quality <= WEB_MAX_QUALITY:
            raise SaveError(f"the starting quality must be between 1 and {WEB_MAX_QUALITY}")
        prefab = find_item(item)
        if any(c not in CHARSETS["letters"] for c in after or ""):
            raise SaveError("cannot continue from that name")
        names, tried, complete = find_names(prefab, quality, MAX_FIRST_RUN, CHARSETS["letters"], 3, 15,
                                            max(1, min(limit, 100)), 8_000_000, after or None)
    except (SaveError, ValueError) as e:
        return json.dumps({"error": str(e)})
    return json.dumps({"item": UPGRADABLE[prefab], "from": quality, "upgrades": MAX_FIRST_RUN, "names": names,
                       "tried": tried, "complete": complete})


WEB_MAX_UPGRADES = 20
WEB_MAX_COPIES = 5
# The most upgrades the kept copy can get in a row (see reaches()), found by trying all 2^32 starting seeds. It is 8 for
# one copy (MAX_FIRST_RUN), and rarer and rarer below that: 13 needs about 1 name in 8 million with two copies, 18 about
# 1 in 2 billion with three. The limit for four and five copies was not worked out.
MAX_REACH = {1: MAX_FIRST_RUN, 2: 13, 3: 18}


def web_find_advanced(item, quality, upgrades, copies, limit, after=""):
    """JSON for the advanced name finder: names where the kept copy gets `upgrades` upgrades, after `copies` - 1 others
    were upgraded until they broke. Each name comes with its upgrade path."""
    try:
        quality, upgrades, copies, limit = int(quality), int(upgrades), int(copies), int(limit)
        if not 1 <= quality <= WEB_MAX_QUALITY:
            raise SaveError(f"the starting quality must be between 1 and {WEB_MAX_QUALITY}")
        if not 1 <= upgrades <= WEB_MAX_UPGRADES:
            raise SaveError(f"the wanted upgrades must be between 1 and {WEB_MAX_UPGRADES}")
        if not 1 <= copies <= WEB_MAX_COPIES:
            raise SaveError(f"the copies must be between 1 and {WEB_MAX_COPIES}")
        if upgrades > MAX_REACH.get(copies, WEB_MAX_UPGRADES):
            raise SaveError(f"{copies} cop{'y' if copies == 1 else 'ies'} cannot get more than {MAX_REACH[copies]} upgrades in a "
                            "row" + ("; use more copies to go further" if copies < max(MAX_REACH) else ""))
        prefab = find_item(item)
        if any(c not in CHARSETS["letters"] for c in after or ""):
            raise SaveError("cannot continue from that name")
        names, tried, complete = find_names(prefab, quality, upgrades, CHARSETS["letters"], 3, 15,
                                            max(1, min(limit, 100)), 8_000_000, after or None, copies, reach=True)
    except (SaveError, ValueError) as e:
        return json.dumps({"error": str(e)})
    return json.dumps({"item": UPGRADABLE[prefab], "from": quality, "upgrades": upgrades, "copies": copies,
                       "names": [{"name": n, "path": upgrade_path(prefab, quality, n, copies, upgrades)} for n in names],
                       "tried": tried, "complete": complete})


def web_predict(data):
    """JSON for the web page's save predictor: what happens to every upgradable item in the character's inventory.

    `data` is the file's bytes (a Uint8Array from the page, or bytes)."""
    try:
        raw = bytes(data.to_py()) if hasattr(data, "to_py") else bytes(data)
        save = load(raw)
        items = run(save)
    except SaveError as e:
        return json.dumps({"error": str(e)})
    items.sort(key=lambda p: (-p["upgrades"], p["name"].lower()))
    return json.dumps({"character": save["name"], "savedSeeds": len(save["seeds"]), "items": items})


def web_predict_item(item, quality, name):
    """JSON for the predictor's manual form: one item at a quality, for a new character with that name (no saved seeds)."""
    try:
        quality = int(quality)
        if not 1 <= quality <= WEB_MAX_QUALITY:
            raise SaveError(f"the quality must be between 1 and {WEB_MAX_QUALITY}")
        if not name:
            raise SaveError("enter a character name")
        prefab = find_item(item)
    except (SaveError, ValueError) as e:
        return json.dumps({"error": str(e)})
    return json.dumps({"character": name, "item": {**predict(prefab, quality, name, {}), "name": UPGRADABLE[prefab],
                                                   "stack": 1}})


def find_names_command(ap, args):
    """--findnameperupgr: needs no save, only the item and the level it starts at."""
    if args.save:
        ap.error("--findnameperupgr works without a save file: a new character has no saved seeds, so only the item and "
                 "its starting level matter. Drop the save path")
    if not args.item:
        ap.error("--findnameperupgr needs a specific item: add --item NAME")
    if args.quality is None:
        ap.error("--findnameperupgr needs the level the item starts at: add --quality N (use 1 for a fresh item)")
    if args.charname is not None or args.check or args.all:
        ap.error("--findnameperupgr cannot be combined with --charname, --check or --all")
    if not 1 <= args.copies <= 5:
        ap.error("--copies must be between 1 and 5")
    if args.quality < 1 or args.findnameperupgr < 0 or args.minlen < 3 or args.maxlen < args.minlen:
        ap.error("need --quality >= 1, N >= 0, --minlen >= 3 and --maxlen >= --minlen")
    if args.findnameperupgr > MAX_FIRST_RUN:
        ap.error(f"no name can give more than {MAX_FIRST_RUN} upgrades before the first break: the first rolls "
                 "of consecutive levels are correlated (all 2^32 starting seeds were checked)")
    try:
        prefab = find_item(args.item)
    except SaveError as e:
        ap.error(str(e))
    maxtries = args.maxtries or (5_000_000 if args.copies == 1 else 200_000_000)
    names, tried, complete = find_names(prefab, args.quality, args.findnameperupgr, CHARSETS[args.charset],
                                        args.minlen, args.maxlen, args.limit, maxtries, copies=args.copies)
    hits = []
    for n in names:
        shared = {}                                 # the seeds the copies leave behind for each other
        runs = [predict(prefab, args.quality, n, shared, update=True) for _ in range(args.copies)]
        hits.append({**runs[0], "name": UPGRADABLE[prefab], "character": n, "copies": runs})
    if args.json:
        print(json.dumps({"item": prefab, "from": args.quality, "upgrades": args.findnameperupgr, "copies": args.copies,
                          "tried": tried, "complete": complete, "names": hits}, indent=1))
        return
    if args.copies == 1:
        more = ""
    elif args.copies == 2:
        more = ", then a second copy reaching the level where the first one broke"
    else:
        more = f", the same for copies 2 to {args.copies - 1}, and copy {args.copies} getting past that level"
    print(f"{UPGRADABLE[prefab]} from level {args.quality}: names where copy 1 gets exactly {args.findnameperupgr} "
          f"upgrade{'s' if args.findnameperupgr != 1 else ''} and breaks{more} "
          f"(a new character, {args.charset}, {tried:,} names tried)")
    for h in hits:
        runs = h["copies"]
        for i, run in enumerate(runs):
            last = args.copies > 1 and i == args.copies - 1
            assert run["upgrades"] >= args.findnameperupgr + (1 if last else 0) and (last or run["broke"]), "name check failed"
        print(f"  {h['character']}" + ("" if args.copies == 1 else
              "   (" + "; ".join(f"copy {i + 1}: {r['upgrades']} upgrades" + (f", breaks going to {r['breaksAt']}" if r["broke"] else "")
                                  for i, r in enumerate(runs)) + ")"))
        if args.verbose:
            for i, run in enumerate(runs):
                if args.copies > 1:
                    print(f"      copy {i + 1}:")
                for st in run["steps"]:
                    print(f"      to level {st['to']}: roll {st['roll']:.4f} -> {st['outcome']}")
    if not hits:
        print("  none found" + ("" if complete else " yet; raise --maxtries or --maxlen"))
    elif len(hits) < args.limit:
        print("  (that is every name in the search range)" if complete else "  (stopped at the --maxtries limit)")


def main():
    ap = argparse.ArgumentParser(description="Predict how many upgrades an item can take before it breaks.")
    ap.add_argument("save", nargs="?", help="path to the .fch character file (not used with --findnameperupgr)")
    ap.add_argument("--item", help="a prefab name or display name (e.g. SwordIron or 'Iron Sword') instead of the inventory")
    ap.add_argument("--quality", type=int, help="level the --item starts at (default: 1; required with --findnameperupgr)")
    ap.add_argument("--all", action="store_true", help="every upgradable item, starting from level 1")
    ap.add_argument("-v", "--verbose", action="store_true", help="show every roll")
    ap.add_argument("--charname", help="predict as if the items belonged to a new character with this name (its first "
                    "rolls start from the name, and it has no saved seeds)")
    ap.add_argument("--findnameperupgr", type=int, metavar="N",
                    help="search for character names whose --item, starting at --quality, gets exactly N upgrades before "
                    "it breaks (needs --item and --quality, takes no save file)")
    ap.add_argument("--copies", type=int, default=1, metavar="N",
                    help="with --findnameperupgr: upgrade N copies of the item one after another with the same character. "
                    "The first N-1 get exactly the wanted upgrades and break; the last one gets past the level where they "
                    "broke (default: 1)")
    ap.add_argument("--charset", choices=sorted(CHARSETS), default="letters",
                    help="characters the name search may use, ASCII only (default: letters)")
    ap.add_argument("--minlen", type=int, default=3, help="shortest name to try (the game needs at least 3; default: 3)")
    ap.add_argument("--maxlen", type=int, default=15, help="longest name to try (default: 15)")
    ap.add_argument("--limit", type=int, default=10, help="stop after this many names (default: 10)")
    ap.add_argument("--maxtries", type=int,
                    help="stop after trying this many names (default: 5000000, or 200000000 with --copies above 1)")
    ap.add_argument("--check", action="store_true", help="compare the saved seeds with the generator")
    ap.add_argument("--json", action="store_true", help="print the result as JSON")
    args = ap.parse_args()
    if args.findnameperupgr is not None:
        find_names_command(ap, args)
        return
    if not args.save:
        ap.error("the path to the .fch character file is required")
    quality = 1 if args.quality is None else args.quality
    try:
        save = load(args.save)
        if args.charname is not None:
            if args.check:
                ap.error("--check compares the saved seeds, which belong to the character in the file; drop --charname")
            save = {**save, "name": args.charname, "seeds": {}}
        if args.check:
            rows = check(save)
            if args.json:
                print(json.dumps(rows, indent=1))
            else:
                show_check(rows)
            return
        results = run(save, args.item, quality, args.all)
    except FileNotFoundError:
        ap.error(f"file not found: {args.save}")
    except OSError as e:
        ap.error(f"cannot read {args.save}: {e.strerror or e}")
    except SaveError as e:
        ap.error(f"{args.save}: {e}")
    if args.json:
        print(json.dumps({"character": save["name"], "savedSeeds": len(save["seeds"]), "items": results}, indent=1))
    else:
        if args.charname is not None:
            print(f"As if the character were named {args.charname!r} (a new character: no saved seeds)")
        else:
            print(f"{save['name']}: {len(save['seeds'])} saved upgrade seed(s)")
        show(results, args.verbose)


if __name__ == "__main__":
    main()
