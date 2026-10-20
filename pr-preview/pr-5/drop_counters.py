#!/usr/bin/env python3
"""drop_counters: how far a character is from each rare creature drop in Valheim.

Reads a Valheim character file (.fch, profile version 46 and up, player data version 34). Python 3, standard library only.

How the game rolls a creature's drops (CharacterDrop.GenerateDropList, as of Valheim 1.0.20):
  * Each star doubles a drop's chance: x1 at 0 stars, x2 at 1 star, x4 at 2 stars. A few drops ignore stars.
  * A final chance above 30% is an independent roll on every kill.
  * A final chance of 30% or less uses a counter instead of luck. With K = int(2 / chance), the first drop comes within
    K kills. After each drop the counter is set to a random number from 0 to K+1, and every kill counts it down by one;
    the kill that takes it to 0 or below drops the item. A saved counter of N therefore means that the N-th kill from
    now drops the item (the next kill when N is 0 or 1).
  * A counter belongs to the item and the final chance (the item's name hash plus int(chance * 1000)), not to a
    creature. Every creature that drops the same item at the same final chance shares it, and each star level of a
    creature has its own, unless the drop ignores stars.
  * The counters live in memory and are saved in the character file. Loading a character, even just showing it on the
    character selection screen, copies its counters into memory but never removes the ones already there, so a
    character picks up the counters it lacks from characters loaded earlier in the same session.
  * In multiplayer the drop is rolled by the client that owns the creature, with that client's counters.
  * The NoPseudoDrops world key turns the counters off; every drop is then an independent roll.

A filter is creature.item (at 0, 1 and 2 stars), creature.N.item (at N stars), creature.N (every drop at N stars) or a
single word (the creature or the item). A name matches anywhere in the prefab name (Greydwarf, TrophyGreydwarf) or the
display name ('Greydwarf trophy'), in any case, so a part of it is enough: greyd.troph. A full name matches just that
one. An empty part or * is anything (.coins, Wolf.*), and * also stands for any run of letters (Mold*Legs).

    python3 drop_counters.py Character.fch                                 # every counter saved in the character
    python3 drop_counters.py Character.fch Greydwarf.TrophyGreydwarf       # one drop at 0, 1 and 2 stars
    python3 drop_counters.py Character.fch Greydwarf.1.TrophyGreydwarf     # ...at 1 star only
    python3 drop_counters.py Character.fch trophy                          # every trophy
    python3 drop_counters.py Character.fch krigen.mold .coins              # parts of names, several filters
    python3 drop_counters.py A.fch B.fch Seeker.TrophySeeker               # several characters
    python3 drop_counters.py 'Troll.*'                                     # no save: only the chances and the rules
"""
import argparse
import fnmatch
import json
import os
import re
import struct
import sys
from collections import defaultdict, namedtuple

PROFILE_MIN_VERSION = 46
PLAYER_DATA_VERSION = 34
STAT_COUNT = 205
SET_COUNT = 10
STARS = (0, 1, 2)           # the star levels a filter without one stands for
SHARED_SHOWN = 3            # how many of the creatures that share a counter to name (all of them with -v)

# BEGIN GENERATED DROPS (tools/update_drop_data.py rewrites everything up to END GENERATED DROPS)
# Creature prefab -> (display name, [(item prefab, drop chance, stars raise the chance), ...]) from each
# creature's CharacterDrop. Chances are the game's 32-bit floats, in the fewest digits that read back the same.
DROPS = {
    'Abomination': ('Abomination', [
        ('TrophyAbomination', 0.5, True),
        ('Root', 1, False),
        ('Guck', 1, False),
    ]),
    'Asksvin': ('Asksvin', [
        ('TrophyAsksvin', 0.1, True),
        ('AskBladder', 1, True),
        ('AskHide', 1, True),
        ('AsksvinMeat', 1, True),
    ]),
    'Asksvin_hatchling': ('Asksvin Hatchling', [
        ('AskBladder', 0.2, True),
        ('AskHide', 0.2, True),
        ('AsksvinMeat', 0.2, True),
    ]),
    'Barka': ('Barka', [
        ('TrophyBarka', 0.1, True),
        ('BarkaBranch', 1, False),
    ]),
    'Bat': ('Bat', [
        ('LeatherScraps', 0.5, False),
    ]),
    'Bat_Swamp': ('Bat', [
        ('LeatherScraps', 0.5, False),
    ]),
    'Bjorn': ('Bear', [
        ('BjornPaw', 1, True),
        ('BjornMeat', 1, True),
        ('BjornHide', 1, True),
        ('TrophyBjorn', 0.1, True),
    ]),
    'Bjorn_sleeping': ('Bear', [
        ('BjornPaw', 1, True),
        ('BjornMeat', 1, True),
        ('BjornHide', 1, True),
        ('TrophyBjorn', 0.1, True),
    ]),
    'Blob': ('Blob', [
        ('TrophyBlob', 0.1, True),
        ('Ooze', 1, True),
    ]),
    'BlobAspect': ('Blob', [
        ('TrophyBlob', 0.1, True),
        ('Ooze', 1, True),
    ]),
    'BlobElite': ('Oozer', [
        ('Ooze', 1, True),
        ('IronScrap', 0.33, True),
        ('TrophyBlob', 0.1, True),
    ]),
    'BlobFrost': ('Frost Blob', [
        ('Crystal', 1, True),
        ('TrophyBlob_Frost', 0.1, True),
    ]),
    'BlobLava': ('Lava Blob', [
        ('ProustitePowder', 1, True),
        ('SulfurStone', 1, True),
        ('TrophyBlob_Lava', 0.1, True),
    ]),
    'BlobMork': ('Shapeless Pulp', [
        ('TrophyBlob_Morkhalla', 0.1, False),
        ('OozeMork', 0.5, True),
    ]),
    'BlobMorkMini': ('Tiny Pulp', [
        ('OozeMork', 0.25, True),
    ]),
    'BlobTar': ('Growth', [
        ('TrophyGrowth', 0.1, True),
        ('Tar', 1, True),
    ]),
    'Boar': ('Boar', [
        ('RawMeat', 1, True),
        ('LeatherScraps', 1, True),
        ('TrophyBoar', 0.15, True),
    ]),
    'BogWitchKvastur': ('Kvastur', [
        ('Wood', 1, True),
        ('Resin', 1, True),
        ('TrophyKvastur', 1, True),
    ]),
    'BogWitch_Camp': ('Kvastur', [
        ('Wood', 1, True),
        ('Resin', 1, True),
        ('TrophyKvastur', 1, True),
    ]),
    'Bonemass': ('Bonemass', [
        ('TrophyBonemass', 1, True),
        ('Wishbone', 1, False),
    ]),
    'BonemawSerpent': ('Bonemaw', [
        ('TrophyBonemawSerpent', 0.33, True),
        ('BoneMawSerpentMeat', 1, True),
        ('BonemawSerpentTooth', 1, True),
    ]),
    'Charred_Archer': ('Charred Marksman', [
        ('CharredBone', 1, True),
        ('TrophyCharredArcher', 0.05, True),
    ]),
    'Charred_Mage': ('Charred Warlock', [
        ('CharredBone', 1, True),
        ('TrophyCharredMage', 0.05, True),
    ]),
    'Charred_Melee': ('Charred Warrior', [
        ('CharredBone', 1, True),
        ('TrophyCharredMelee', 0.05, True),
    ]),
    'Charred_Melee_Dyrnwyn': ('<color=orange>Lord Reto</color>', [
        ('DyrnwynHiltFragment', 1, False),
    ]),
    'Charred_Twitcher': ('Charred Twitcher', [
        ('CharredBone', 1, True),
    ]),
    'Charred_Twitcher_Summoned': ('Summoned Twitcher', [
        ('CharredBone', 1, True),
    ]),
    'Chicken': ('Chicken', [
        ('ChickenMeat', 0.25, True),
        ('Feathers', 0.5, True),
    ]),
    'Deathsquito': ('Deathsquito', [
        ('Needle', 1, False),
        ('TrophyDeathsquito', 0.05, True),
    ]),
    'Deer': ('Deer', [
        ('DeerMeat', 1, True),
        ('DeerHide', 1, True),
        ('TrophyDeer', 0.5, True),
    ]),
    'Deer_White': ('Deer_White', [
        ('DeerMeat', 1, True),
        ('TrophyDeerWhite', 1, True),
    ]),
    'DevCombatRing': ('DevCombatRing', [
        ('Entrails', 0.5, True),
        ('TrophyDraugr', 0.1, True),
    ]),
    'Dragon': ('Moder', [
        ('TrophyDragonQueen', 1, True),
        ('DragonTear', 1, False),
    ]),
    'Draugr': ('Draugr', [
        ('Entrails', 1, True),
        ('TrophyDraugr', 0.1, True),
    ]),
    'Draugr_Elite': ('Draugr Elite', [
        ('Entrails', 1, True),
        ('TrophyDraugrElite', 0.1, True),
    ]),
    'Draugr_Elite_sleeping': ('Draugr Elite', [
        ('Entrails', 1, True),
        ('TrophyDraugrElite', 0.1, True),
    ]),
    'Draugr_Ranged': ('Draugr', [
        ('Entrails', 1, True),
        ('TrophyDraugr', 0.1, True),
    ]),
    'Draugr_Ranged_sleeping': ('Draugr', [
        ('Entrails', 1, True),
        ('TrophyDraugr', 0.1, True),
    ]),
    'Draugr_sleeping': ('Draugr', [
        ('Entrails', 1, True),
        ('TrophyDraugr', 0.1, True),
    ]),
    'Dverger': ('Dvergr Rogue', [
        ('Softtissue', 0.25, False),
        ('BlackMarble', 0.5, False),
        ('Coins', 1, False),
        ('TrophyDvergr', 0.05, True),
    ]),
    'DvergerAshlands': ('Dvergr Rogue', [
        ('Softtissue', 0.25, False),
        ('BlackMarble', 0.5, False),
        ('Coins', 1, False),
        ('TrophyDvergr', 0.05, True),
    ]),
    'DvergerDeepNorth': ('Imprisoned Dvergr', [
        ('Coins', 1, True),
        ('TrophyDvergr', 0.05, False),
        ('AncientGemstoneBlack', 0.1, True),
        ('AncientGemstoneGreen', 0.1, True),
        ('AncientGemstoneOrange', 0.1, True),
        ('AncientGemstonePurple', 0.1, True),
    ]),
    'DvergerMage': ('Dvergr Mage', [
        ('Softtissue', 0.25, False),
        ('BlackMarble', 0.5, False),
        ('Coins', 1, False),
        ('TrophyDvergr', 0.05, True),
    ]),
    'DvergerMageFire': ('Dvergr Mage', [
        ('Softtissue', 0.25, False),
        ('BlackMarble', 0.5, False),
        ('Coins', 1, False),
        ('TrophyDvergr', 0.05, True),
    ]),
    'DvergerMageIce': ('Dvergr Mage', [
        ('Softtissue', 0.25, False),
        ('BlackMarble', 0.5, False),
        ('Coins', 1, False),
        ('TrophyDvergr', 0.05, True),
    ]),
    'DvergerMageSupport': ('Dvergr Mage', [
        ('Softtissue', 0.25, False),
        ('BlackMarble', 0.5, False),
        ('Coins', 1, False),
        ('TrophyDvergr', 0.05, True),
    ]),
    'DvergerTest': ('DvergerTest', [
        ('Coins', 0.25, True),
        ('BlackMetalScrap', 1, True),
        ('Pukeberries', 1, True),
        ('TrophyGoblinShaman', 0.1, False),
    ]),
    'Eikthyr': ('Eikthyr', [
        ('TrophyEikthyr', 1, True),
        ('HardAntler', 1, False),
    ]),
    'Elaking': ('Elaking', [
        ('ElakingHairBundle', 1, True),
        ('TrophyElaking', 0.1, True),
        ('MoldKeys', 0.2, False),
    ]),
    'ElakingLantern': ('Elaking', [
        ('ElakingHairBundle', 1, True),
        ('TrophyElaking', 0.1, True),
    ]),
    'ElakingMole': ('Eyeless One', [
        ('TrophyMole', 0.1, True),
        ('MoleClaws', 1, True),
        ('MoldKeys', 0.5, False),
    ]),
    'Fader': ('Fader', [
        ('TrophyFader', 1, True),
        ('FaderDrop', 1, False),
    ]),
    'FallenValkyrie': ('Fallen Valkyrie', [
        ('CelestialFeather', 1, True),
        ('TrophyFallenValkyrie', 0.05, True),
    ]),
    'FallenWarrior': ('Fallen Warrior', [
        ('OrbFrostFire', 0.5, False),
        ('OrbThunderBlood', 0.5, False),
    ]),
    'Fenring': ('Fenring', [
        ('WolfFang', 1, True),
        ('TrophyFenring', 0.1, True),
    ]),
    'Fenring_Cultist': ('Cultist', [
        ('JuteRed', 1, True),
        ('TrophyCultist', 0.1, True),
    ]),
    'Fenring_Cultist_Hildir': ('<color=orange>Geirrhafa</color>', [
        ('chest_hildir2', 1, False),
        ('TrophyCultist_Hildir', 1, True),
    ]),
    'Fenring_Cultist_Hildir_nochest': ('<color=orange>Geirrhafa</color>', [
        ('TrophyCultist_Hildir', 1, False),
    ]),
    'FrostWisp': ('FrostWisp', [
        ('LeatherScraps', 0.5, False),
    ]),
    'FrozenKing_p3': ('Kall Fimbulbringer', [
        ('FrozenKingDrop', 1, False),
        ('CrownJewel', 1, False),
    ]),
    'Frysling': ('Frysling', [
        ('FrostCore', 1, True),
    ]),
    'Ghost': ('Ghost', [
        ('Ectoplasm', 1, False),
        ('TrophyGhost', 0.1, True),
    ]),
    'Ghost_Void': ('The Void', [
        ('KnifeVoid', 1, False),
    ]),
    'Ghost_old': ('The Void', [
        ('Ectoplasm', 0.5, False),
    ]),
    'Ghost_sleeping': ('Ghost', [
        ('Ectoplasm', 1, False),
        ('TrophyGhost', 0.1, True),
    ]),
    'Gjall': ('Gjall', [
        ('Bilebag', 1, False),
        ('TrophyGjall', 0.3, True),
    ]),
    'Goblin': ('Fuling', [
        ('Coins', 0.25, True),
        ('BlackMetalScrap', 1, True),
        ('TrophyGoblin', 0.1, True),
    ]),
    'GoblinArcher': ('Fuling', [
        ('Coins', 0.25, True),
        ('BlackMetalScrap', 1, True),
        ('TrophyGoblin', 0.1, True),
    ]),
    'GoblinBrute': ('Fuling Berserker', [
        ('Coins', 1, True),
        ('BlackMetalScrap', 1, True),
        ('GoblinTotem', 0.1, False),
        ('TrophyGoblinBrute', 0.05, True),
    ]),
    'GoblinBruteBros': ('<color=orange>Zil & Thungr</color>', [
        ('TrophyGoblinBruteBrosBrute', 1, True),
    ]),
    'GoblinBruteBros_nochest': ('<color=orange>Zil & Thungr</color>', [
        ('TrophyGoblinBruteBrosBrute', 1, True),
    ]),
    'GoblinBrute_Hildir': ('<color=orange>Thungr</color> ', [
        ('chest_hildir3', 1, False),
    ]),
    'GoblinDeepNorth': ('Captive Fuling', [
        ('Coins', 0.25, True),
        ('AncientCoin', 1, True),
        ('Lingonberry', 0.2, True),
    ]),
    'GoblinKing': ('Yagluth', [
        ('TrophyGoblinKing', 1, False),
        ('YagluthDrop', 1, False),
    ]),
    'GoblinShaman': ('Fuling Shaman', [
        ('Coins', 0.25, True),
        ('BlackMetalScrap', 1, True),
        ('Pukeberries', 1, True),
        ('TrophyGoblinShaman', 0.1, False),
    ]),
    'GoblinShaman_Hildir': ('<color=orange>Zil</color> ', [
        ('chest_hildir3', 1, False),
        ('TrophyGoblinBruteBrosShaman', 1, True),
    ]),
    'GoblinShaman_Hildir_nochest': ('<color=orange>Zil</color> ', [
        ('TrophyGoblinBruteBrosShaman', 1, False),
    ]),
    'Goblin_Gem': ('Riktig Fuling', [
        ('GemstoneBlue', 1, True),
        ('GemstoneGreen', 1, True),
        ('GemstoneRed', 1, True),
    ]),
    'Greydwarf': ('Greydwarf', [
        ('GreydwarfEye', 0.5, True),
        ('Stone', 1, True),
        ('Wood', 1, True),
        ('Resin', 1, True),
        ('TrophyGreydwarf', 0.05, True),
    ]),
    'Greydwarf_Elite': ('Greydwarf Brute', [
        ('GreydwarfEye', 0.5, True),
        ('Stone', 1, True),
        ('Wood', 1, True),
        ('Dandelion', 1, True),
        ('AncientSeed', 0.33, True),
        ('TrophyGreydwarfBrute', 0.1, True),
    ]),
    'Greydwarf_Frozen': ('Greydwarf', [
        ('GreydwarfEye', 0.5, True),
        ('Wood', 1, True),
        ('Resin', 1, True),
        ('TrophyGreydwarf', 0.05, False),
        ('Snowball', 1, True),
        ('Ice', 1, True),
    ]),
    'Greydwarf_Shaman': ('Greydwarf Shaman', [
        ('GreydwarfEye', 0.5, True),
        ('Wood', 1, True),
        ('Resin', 1, True),
        ('TrophyGreydwarfShaman', 0.1, True),
        ('Pukeberries', 1, True),
    ]),
    'Greydwarf_Shaman_Frozen': ('Greydwarf Shaman', [
        ('GreydwarfEye', 0.5, True),
        ('Wood', 1, True),
        ('Resin', 1, True),
        ('TrophyGreydwarfShaman', 0.1, False),
        ('Pukeberries', 1, True),
        ('Ice', 1, True),
    ]),
    'Greyling': ('Greyling', [
        ('Resin', 1, True),
    ]),
    'Hare': ('Hare', [
        ('HareMeat', 1, True),
        ('ScaleHide', 1, True),
        ('TrophyHare', 0.05, True),
    ]),
    'Hatchling': ('Drake', [
        ('TrophyHatchling', 0.1, True),
        ('FreezeGland', 1, True),
    ]),
    'Hen': ('Hen', [
        ('ChickenMeat', 1, True),
        ('Feathers', 1, True),
    ]),
    'Hive': ('Hive', [
        ('TrophySeekerQueen', 1, False),
        ('QueenDrop', 1, False),
    ]),
    'JotunWarrior': ('Krigen', [
        ('MoldArmormediumChest', 0.03, True),
        ('MoldArmorMediumHelmet', 0.03, True),
        ('MoldArmorMediumLegs', 0.03, True),
        ('MemorialCoal', 0.2, True),
        ('TrophyJotunWarrior', 0.1, True),
        ('Leatherstraps', 1, True),
        ('MoldArmorGoldLegs', 0.03, True),
        ('MoldArmorGoldChest', 0.03, True),
        ('MoldArmorGoldHelmet', 0.03, True),
    ]),
    'JotunWarriorDualWield': ('Krigen', [
        ('MoldArmormediumChest', 0.03, True),
        ('MoldArmorMediumHelmet', 0.03, True),
        ('MoldArmorMediumLegs', 0.03, True),
        ('MemorialCoal', 0.2, True),
        ('TrophyJotunWarrior', 0.1, True),
        ('Leatherstraps', 1, True),
        ('MoldArmorGoldLegs', 0.03, True),
        ('MoldArmorGoldChest', 0.03, True),
        ('MoldArmorGoldHelmet', 0.03, True),
    ]),
    'JotunWitch': ('Hexen', [
        ('NornThread', 1, True),
        ('TrophyJotunWitch', 0.1, True),
        ('BloodGoldKey', 0.1, False),
        ('MoldArmorMageChest', 0.05, False),
        ('MoldArmorMageHelmet', 0.05, False),
        ('MoldArmorMageLegs', 0.05, False),
    ]),
    'Leech': ('Leech', [
        ('TrophyLeech', 0.1, True),
        ('Bloodbag', 1, True),
    ]),
    'Leech_cave': ('Leech', [
        ('TrophyLeech', 0.1, False),
        ('Bloodbag', 1, True),
    ]),
    'Lox': ('Lox', [
        ('LoxMeat', 1, True),
        ('TrophyLox', 0.1, True),
        ('LoxPelt', 1, True),
    ]),
    'Lox_Calf': ('Lox Calf', [
        ('LoxMeat', 1, False),
    ]),
    'Moose': ('Moose', [
        ('MooseMeat', 1, True),
        ('TrophyMoose', 0.1, True),
        ('MooseHide', 1, True),
        ('MooseSinew', 1, True),
    ]),
    'Morgen': ('Morgen', [
        ('MorgenSinew', 1, True),
        ('MorgenHeart', 0.8, True),
        ('TrophyMorgen', 0.05, True),
    ]),
    'Morgen_NonSleeping': ('Morgen', [
        ('MorgenSinew', 1, True),
        ('MorgenHeart', 0.8, True),
        ('TrophyMorgen', 0.05, True),
    ]),
    'Neck': ('Neck', [
        ('NeckTail', 0.7, True),
        ('TrophyNeck', 0.05, True),
    ]),
    'Seal': ('Seal', [
        ('SealHide', 1, True),
        ('TrophySeal', 0.1, True),
        ('SealBlubber', 1, True),
    ]),
    'Seal_Pup': ('Baby Seal', [
        ('SealBlubber', 0.1, True),
    ]),
    'Seeker': ('Seeker', [
        ('BugMeat', 1, True),
        ('Carapace', 1, True),
        ('TrophySeeker', 0.05, True),
    ]),
    'SeekerBrood': ('Seeker Brood', [
        ('RoyalJelly', 0.5, False),
    ]),
    'SeekerBrute': ('Seeker Soldier', [
        ('BugMeat', 1, True),
        ('Carapace', 1, True),
        ('TrophySeekerBrute', 0.05, True),
        ('Mandible', 1, False),
    ]),
    'SeekerQueen': ('The Queen', [
        ('TrophySeekerQueen', 1, True),
        ('QueenDrop', 1, False),
    ]),
    'Serpent': ('Serpent', [
        ('TrophySerpent', 0.33, True),
        ('SerpentMeat', 1, True),
        ('SerpentScale', 1, True),
    ]),
    'Skeleton': ('Skeleton', [
        ('TrophySkeleton', 0.1, True),
        ('BoneFragments', 1, True),
    ]),
    'Skeleton_DeepNorth': ('Skeleton', [
        ('TrophySkeleton', 0.1, True),
        ('BoneFragments', 1, True),
        ('Ice', 1, True),
    ]),
    'Skeleton_Hildir': ('<color=orange>Brenna</color>', [
        ('chest_hildir1', 1, False),
        ('TrophySkeletonHildir', 1, True),
    ]),
    'Skeleton_Hildir_nochest': ('<color=orange>Brenna</color>', [
        ('TrophySkeletonHildir', 1, False),
    ]),
    'Skeleton_Meadows': ('Skeleton', [
        ('TrophySkeleton', 0.1, True),
        ('BoneFragments', 1, True),
    ]),
    'Skeleton_Meadows_noarcher': ('Skeleton', [
        ('TrophySkeleton', 0.1, False),
        ('BoneFragments', 1, True),
    ]),
    'Skeleton_Mountains': ('Skeleton', [
        ('TrophySkeleton', 0.1, True),
        ('BoneFragments', 1, True),
    ]),
    'Skeleton_Mountains_noarcher': ('Skeleton', [
        ('TrophySkeleton', 0.1, True),
        ('BoneFragments', 1, True),
    ]),
    'Skeleton_NoArcher': ('Skeleton', [
        ('TrophySkeleton', 0.1, True),
        ('BoneFragments', 1, True),
    ]),
    'Skeleton_Poison': ('Rancid Remains', [
        ('TrophySkeletonPoison', 0.1, True),
        ('BoneFragments', 1, True),
    ]),
    'Skeleton_Swamps': ('Skeleton', [
        ('TrophySkeleton', 0.1, True),
        ('BoneFragments', 1, True),
    ]),
    'Skeleton_Swamps_noarcher': ('Skeleton', [
        ('TrophySkeleton', 0.1, True),
        ('BoneFragments', 1, True),
    ]),
    'Skeleton_aspect': ('Skeleton', [
        ('TrophySkeleton', 0.1, True),
        ('BoneFragments', 1, True),
    ]),
    'StoneGolem': ('Stone Golem', [
        ('TrophySGolem', 0.05, True),
        ('Stone', 1, True),
        ('Crystal', 1, True),
    ]),
    'Surtling': ('Surtling', [
        ('Coal', 1, True),
        ('SurtlingCore', 0.5, True),
        ('TrophySurtling', 0.05, True),
    ]),
    'TheHive': ('TheHive', [
        ('TrophyHatchling', 0.1, False),
        ('FreezeGland', 1, True),
    ]),
    'Tick': ('Tick', [
        ('GiantBloodSack', 1, False),
        ('TrophyTick', 0.05, True),
    ]),
    'TrainingDummy': ('TrainingDummy', [
        ('Entrails', 0.5, True),
        ('TrophyDraugr', 0.1, True),
    ]),
    'Troll': ('Troll', [
        ('Coins', 1, True),
        ('TrophyFrostTroll', 0.5, True),
        ('TrollHide', 1, True),
    ]),
    'Troll_sleeping': ('Troll', [
        ('Coins', 1, True),
        ('TrophyFrostTroll', 0.5, True),
        ('TrollHide', 1, True),
    ]),
    'Ulv': ('Ulv', [
        ('WolfFang', 0.5, False),
        ('TrophyUlv', 0.1, True),
    ]),
    'Unbjorn': ('Vile', [
        ('TrophyBjornUndead', 0.1, True),
        ('BjornMeat', 1, True),
        ('RottenMeat', 0.8, True),
        ('UndeadBjornRibcage', 1, True),
        ('BjornHide', 1, True),
    ]),
    'Volture': ('Volture', [
        ('TrophyVolture', 0.1, True),
        ('VoltureMeat', 1, False),
        ('Feathers', 0.5, False),
        ('VoltureEgg', 0.5, False),
    ]),
    'Wolf': ('Wolf', [
        ('TrophyWolf', 0.1, True),
        ('WolfMeat', 1, True),
        ('WolfPelt', 1, True),
        ('WolfFang', 0.4, True),
    ]),
    'Wraith': ('Wraith', [
        ('TrophyWraith', 0.05, True),
        ('Chain', 1, True),
    ]),
    'Writhan': ('Writhan', [
        ('TrophyWrithan', 0.1, True),
        ('WrithanRoots', 1, True),
    ]),
    'dvergr_new_bossroom_ENTRANCE02': ('The Queen', [
        ('TrophySeekerQueen', 1, True),
        ('QueenDrop', 1, False),
    ]),
    'gd_king': ('The Elder', [
        ('TrophyTheElder', 1, True),
        ('CryptKey', 1, False),
    ]),
    'memorialsite_offering': ('Fallen Warrior', [
        ('OrbFrostFire', 0.5, False),
        ('OrbThunderBlood', 0.5, False),
    ]),
}
# Item prefab -> display name, for every item in DROPS.
ITEM_NAMES = {
    'AncientCoin': 'Ancient Coin',
    'AncientGemstoneBlack': 'Draumyx',
    'AncientGemstoneGreen': 'Grimvarn',
    'AncientGemstoneOrange': 'Solryth',
    'AncientGemstonePurple': 'Veydris',
    'AncientSeed': 'Ancient Seed',
    'AskBladder': 'Asksvin Bladder',
    'AskHide': 'Asksvin Hide',
    'AsksvinMeat': 'Asksvin Tail',
    'BarkaBranch': 'Frozen Branch',
    'Bilebag': 'Bilebag',
    'BjornHide': 'Bear Hide',
    'BjornMeat': 'Bear Meat',
    'BjornPaw': 'Bear Paw',
    'BlackMarble': 'Black Marble',
    'BlackMetalScrap': 'Black Metal Scrap',
    'BloodGoldKey': 'Intricate Key',
    'Bloodbag': 'Bloodbag',
    'BoneFragments': 'Bone Fragments',
    'BoneMawSerpentMeat': 'Bonemaw Meat',
    'BonemawSerpentTooth': 'Bonemaw Tooth',
    'BugMeat': 'Seeker Meat',
    'Carapace': 'Carapace',
    'CelestialFeather': 'Celestial Feather',
    'Chain': 'Chain',
    'CharredBone': 'Charred Bone',
    'ChickenMeat': 'Chicken Meat',
    'Coal': 'Coal',
    'Coins': 'Coins',
    'CrownJewel': 'Crown Jewel',
    'CryptKey': 'Swamp Key',
    'Crystal': 'Crystal',
    'Dandelion': 'Dandelion',
    'DeerHide': 'Deer Hide',
    'DeerMeat': 'Deer Meat',
    'DragonTear': 'Dragon Tear',
    'DyrnwynHiltFragment': 'Dyrnwyn Hilt Fragment',
    'Ectoplasm': 'Ectoplasm',
    'ElakingHairBundle': 'Elaking Hair Bundle',
    'Entrails': 'Entrails',
    'FaderDrop': 'Kindled Ribs',
    'Feathers': 'Feathers',
    'FreezeGland': 'Freeze Gland',
    'FrostCore': 'Frostcore',
    'FrozenKingDrop': 'Sacrificial Blood',
    'GemstoneBlue': 'Iolite',
    'GemstoneGreen': 'Jade',
    'GemstoneRed': 'Bloodstone',
    'GiantBloodSack': 'Blood Clot',
    'GoblinTotem': 'Fuling Totem',
    'GreydwarfEye': 'Greydwarf Eye',
    'Guck': 'Guck',
    'HardAntler': 'Hard Antler',
    'HareMeat': 'Hare Meat',
    'Ice': 'Ice',
    'IronScrap': 'Scrap Iron',
    'JuteRed': 'Red Jute',
    'KnifeVoid': 'Voidcaller',
    'LeatherScraps': 'Leather Scraps',
    'Leatherstraps': 'Leather Straps',
    'Lingonberry': 'Lingonberries',
    'LoxMeat': 'Lox Meat',
    'LoxPelt': 'Lox Pelt',
    'Mandible': 'Mandible',
    'MemorialCoal': 'Memorial Coal',
    'MoldArmorGoldChest': 'Mould: Breastplate of the Protector',
    'MoldArmorGoldHelmet': 'Mould: Helmet of the Protector',
    'MoldArmorGoldLegs': 'Mould: Trousers of the Protector',
    'MoldArmorMageChest': 'Mould: Robes of the Caller',
    'MoldArmorMageHelmet': 'Mould: Headdress of the Caller',
    'MoldArmorMageLegs': 'Mould: Trousers of the Caller',
    'MoldArmorMediumHelmet': 'Mould: Hood of the Vanguard',
    'MoldArmorMediumLegs': 'Mould: Trousers of the Vanguard',
    'MoldArmormediumChest': 'Mould: Chestpiece of the Vanguard',
    'MoldKeys': 'Mould: Intricate Key',
    'MoleClaws': 'Long Claws',
    'MooseHide': 'Moose Hide',
    'MooseMeat': 'Moose Meat',
    'MooseSinew': 'Moose Sinew',
    'MorgenHeart': 'Morgen Heart',
    'MorgenSinew': 'Morgen Sinew',
    'NeckTail': 'Neck Tail',
    'Needle': 'Needle',
    'NornThread': 'Nornathread',
    'Ooze': 'Ooze',
    'OozeMork': 'Dead Pulp',
    'OrbFrostFire': 'Frostfire Essence',
    'OrbThunderBlood': 'Thunderblood Essence',
    'ProustitePowder': 'Proustite Powder',
    'Pukeberries': 'Bukeperries',
    'QueenDrop': 'Majestic Carapace',
    'RawMeat': 'Boar Meat',
    'Resin': 'Resin',
    'Root': 'Root',
    'RottenMeat': 'Rotten Meat',
    'RoyalJelly': 'Royal Jelly',
    'ScaleHide': 'Scale Hide',
    'SealBlubber': 'Seal Blubber',
    'SealHide': 'Seal Pelt',
    'SerpentMeat': 'Serpent Meat',
    'SerpentScale': 'Serpent Scale',
    'Snowball': 'Snowball',
    'Softtissue': 'Soft Tissue',
    'Stone': 'Stone',
    'SulfurStone': 'Sulfur',
    'SurtlingCore': 'Surtling Core',
    'Tar': 'Tar',
    'TrollHide': 'Troll Hide',
    'TrophyAbomination': 'Abomination Trophy',
    'TrophyAsksvin': 'Asksvin Trophy',
    'TrophyBarka': 'Barka Trophy',
    'TrophyBjorn': 'Bear Trophy',
    'TrophyBjornUndead': 'Vile Trophy',
    'TrophyBlob': 'Blob Trophy',
    'TrophyBlob_Frost': 'Frost Blob Trophy',
    'TrophyBlob_Lava': 'Lava Blob Trophy',
    'TrophyBlob_Morkhalla': 'Pulp Trophy',
    'TrophyBoar': 'Boar Trophy',
    'TrophyBonemass': 'Bonemass Trophy',
    'TrophyBonemawSerpent': 'Bonemaw Trophy',
    'TrophyCharredArcher': 'Marksman Trophy',
    'TrophyCharredMage': 'Warlock Trophy',
    'TrophyCharredMelee': 'Warrior Trophy',
    'TrophyCultist': 'Cultist Trophy',
    'TrophyCultist_Hildir': 'Geirrhafa Trophy',
    'TrophyDeathsquito': 'Deathsquito Trophy',
    'TrophyDeer': 'Deer Trophy',
    'TrophyDeerWhite': 'TrophyDeerWhite',
    'TrophyDragonQueen': 'Moder Trophy',
    'TrophyDraugr': 'Draugr Trophy',
    'TrophyDraugrElite': 'Draugr Elite Trophy',
    'TrophyDvergr': 'Dvergr Trophy',
    'TrophyEikthyr': 'Eikthyr Trophy',
    'TrophyElaking': 'Elaking Trophy',
    'TrophyFader': 'Fader Trophy',
    'TrophyFallenValkyrie': 'Fallen Valkyrie Trophy',
    'TrophyFenring': 'Fenring Trophy',
    'TrophyFrostTroll': 'Troll Trophy',
    'TrophyGhost': 'Ghost Trophy',
    'TrophyGjall': 'Gjall Trophy',
    'TrophyGoblin': 'Fuling Trophy',
    'TrophyGoblinBrute': 'Fuling Berserker Trophy',
    'TrophyGoblinBruteBrosBrute': 'Thungr Trophy',
    'TrophyGoblinBruteBrosShaman': 'Zil Trophy',
    'TrophyGoblinKing': 'Yagluth Trophy',
    'TrophyGoblinShaman': 'Fuling Shaman Trophy',
    'TrophyGreydwarf': 'Greydwarf Trophy',
    'TrophyGreydwarfBrute': 'Greydwarf Brute Trophy',
    'TrophyGreydwarfShaman': 'Greydwarf Shaman Trophy',
    'TrophyGrowth': 'Growth Trophy',
    'TrophyHare': 'Hare Trophy',
    'TrophyHatchling': 'Drake Trophy',
    'TrophyJotunWarrior': 'Krigen Trophy',
    'TrophyJotunWitch': 'Hexen Trophy',
    'TrophyKvastur': 'Kvastur',
    'TrophyLeech': 'Leech Trophy',
    'TrophyLox': 'Lox Trophy',
    'TrophyMole': 'Eyeless One Trophy',
    'TrophyMoose': 'Moose Trophy',
    'TrophyMorgen': 'Morgen Trophy',
    'TrophyNeck': 'Neck Trophy',
    'TrophySGolem': 'Stone Golem Trophy',
    'TrophySeal': 'Seal Trophy',
    'TrophySeeker': 'Seeker Trophy',
    'TrophySeekerBrute': 'Seeker Soldier Trophy',
    'TrophySeekerQueen': 'The Queen Trophy',
    'TrophySerpent': 'Serpent Trophy',
    'TrophySkeleton': 'Skeleton Trophy',
    'TrophySkeletonHildir': 'Brenna Trophy',
    'TrophySkeletonPoison': 'Rancid Remains Trophy',
    'TrophySurtling': 'Surtling Trophy',
    'TrophyTheElder': 'The Elder Trophy',
    'TrophyTick': 'Tick Trophy',
    'TrophyUlv': 'Ulv Trophy',
    'TrophyVolture': 'Volture Trophy',
    'TrophyWolf': 'Wolf Trophy',
    'TrophyWraith': 'Wraith Trophy',
    'TrophyWrithan': 'Writhan Trophy',
    'UndeadBjornRibcage': 'Vile Ribcage',
    'VoltureEgg': 'Volture Egg',
    'VoltureMeat': 'Volture Meat',
    'Wishbone': 'Wishbone',
    'WolfFang': 'Wolf Fang',
    'WolfMeat': 'Wolf Meat',
    'WolfPelt': 'Wolf Pelt',
    'Wood': 'Wood',
    'WrithanRoots': 'Writhan Roots',
    'YagluthDrop': 'Torn Spirit',
    'chest_hildir1': "Hildir's Brass Chest",
    'chest_hildir2': "Hildir's Silver Chest",
    'chest_hildir3': "Hildir's Bronze Chest",
}
# END GENERATED DROPS


class SaveError(Exception):
    """The input is not a save this tool can read."""


# ---------------------------------------------------------------------------------------------------------------
# The game's numbers
# ---------------------------------------------------------------------------------------------------------------

M32 = 0xFFFFFFFF


def f32(x):
    """Round to a 32-bit float, as the game stores its numbers."""
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


PITY_LIMIT = f32(0.3)       # chances up to this one use a counter (the game compares with the float 0.3, so 15% at 1 star does)


def final_chance(chance, scales, stars):
    """The drop chance at a star level: each star doubles it, unless the drop ignores stars."""
    return f32(f32(chance) * (2 ** stars if scales else 1))


def counter_key(item, chance):
    """The key of the counter that a drop with this final chance uses, or None when the drop is an independent roll."""
    if not 0 < chance <= PITY_LIMIT:
        return None
    # Mono works this out in double precision on the float chance: 3% is 0.0299999993 as a float and gives 29, not 30
    return s32(stable_hash(item) + int(chance * 1000))


def first_drop_within(chance):
    """K: the first drop comes within K kills, and the gap between two drops is 1 to K+1 kills."""
    return int(1 / chance * 2)


# ---------------------------------------------------------------------------------------------------------------
# Reading the save
# ---------------------------------------------------------------------------------------------------------------

class Reader:
    def __init__(self, data):
        self.d, self.p = data, 0

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


def skip_item(r):
    """One ItemDrop.ItemData as saved (item version 110)."""
    r.skip(4 + 3)                               # durability * 100, grid x, grid y, world level
    flags = r.take("B")
    r.skip((2 if flags & 4 else 0) + (2 if flags & 8 else 0) + (4 if flags & 16 else 0))   # quality, stack, variant
    if flags & 32:
        r.skip(8)                               # crafter id
        r.string()                              # crafter name
    if flags & 64:
        r.skip(4)                               # prefab hash
    if flags & 128:
        for _ in range(r.num_items()):          # custom data
            r.string()
            r.string()
    r.skip(1)                                   # cheated flag


def load(source):
    """The character name and the drop counters ({counter key: value}) of a save (a path or bytes)."""
    if isinstance(source, (bytes, bytearray)):
        raw = bytes(source)
    else:
        with open(source, "rb") as f:
            raw = f.read()
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
        player_version = r.take("i")
        if player_version < PLAYER_DATA_VERSION:
            # version 34 (Valheim 1.0.20) started saving the counters; before, they were lost when the game closed
            raise SaveError(f"this character was last saved by an older Valheim version (player data version "
                            f"{player_version}), which did not keep the drop counters in the character file. Load the "
                            "character in the current Valheim (1.0.20 or newer) and save it there first")
        if player_version != PLAYER_DATA_VERSION:
            raise SaveError("the player data format changed and the script needs updating")
        r.skip(16)                              # max health, health, max stamina, time since death
        r.string()                              # guardian power
        r.skip(4)                               # guardian power cooldown
        r.skip(4)                               # inventory version
        for _ in range(r.take("H")):
            skip_item(r)
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
        counters = {}
        for _ in range(r.take("i")):
            key = r.take("i")
            counters[key] = r.take("i")
        r.skip(r.take("i") * 8)                 # upgrade seeds
        if r.p != blob_end:
            raise SaveError("the player data has an unexpected layout and the script needs updating")
    except SaveError:
        raise
    except (struct.error, IndexError, UnicodeDecodeError, OverflowError):
        raise SaveError("this is not a supported Valheim .fch character file, or its layout changed and the script "
                        "needs updating")
    return name, counters


# ---------------------------------------------------------------------------------------------------------------
# Drops and filters
# ---------------------------------------------------------------------------------------------------------------

Row = namedtuple("Row", "creature stars item chance scales key")


def label(row):
    return f"{row.creature}.{row.stars}.{row.item}"


def rows_at(levels):
    """Every drop of every creature at these star levels."""
    for creature in sorted(DROPS):
        for item, chance, scales in DROPS[creature][1]:
            for stars in levels:
                p = final_chance(chance, scales, stars)
                yield Row(creature, stars, item, p, scales, counter_key(item, p))


def by_counter(rows):
    index = defaultdict(list)
    for row in rows:
        if row.key is not None:
            index[row.key].append(row)
    return index


def is_stars(part):
    return part in ("", "*") or part.isdigit()


def parse_filter(text):
    """A filter -> (creature pattern, star levels, item pattern, whether a match on either one is enough).

    word                 the creature or the item       (trophy, krigen)
    creature.item        at 0, 1 and 2 stars            (Greydwarf.TrophyGreydwarf, greyd.troph, .coins)
    creature.N.item      at N stars                     (Greydwarf.1.TrophyGreydwarf)
    creature.N           every drop at N stars          (Wolf.2)
    An empty part or * is anything, and a trailing .* adds nothing, so the regex habit .*Trophy.* works too. A filter
    that still makes no sense is read once more with every .* inside a part as * (.*Mold.*Legs is *Mold*Legs)."""
    try:
        return parse_parts(text)
    except ValueError:
        regex = re.sub(r"\.\*(?!\.)", "*", text)
        if regex == text:
            raise
        try:
            return parse_parts(regex)
        except ValueError:
            pass
        raise


def parse_parts(text):
    parts = [p.strip() for p in text.split(".")]
    while len(parts) > 2 and parts[-1] in ("", "*") and not (len(parts) == 3 and is_stars(parts[1])):
        parts.pop()
    if len(parts) == 1:
        return parts[0], STARS, parts[0], True
    if len(parts) == 2:
        if parts[1].isdigit():
            return parts[0], (int(parts[1]),), "", False
        return parts[0], STARS, parts[1], False
    if len(parts) == 3 and is_stars(parts[1]):
        return parts[0], STARS if not parts[1].isdigit() else (int(parts[1]),), parts[2], False
    raise ValueError(f"{text!r} is not a filter: use a name (trophy), creature.item (greyd.troph) or creature.N.item "
                     "(Greydwarf.1.TrophyGreydwarf)")


def matching(pattern, names):
    """The prefab names (a dict's keys, display names as values) that a pattern matches, in any case.

    An empty pattern or * matches everything. A full prefab name, or else a full display name, matches just that one
    (Greydwarf is not also Greydwarf_Frozen; Krigen is both Jotun warriors). Anything else matches anywhere in the
    prefab or display name, with * for any run of letters (greyd, troph, Mold*Legs)."""
    pattern = pattern.lower()
    if pattern in ("", "*"):
        return set(names)
    exact = {k for k in names if k.lower() == pattern} or {k for k, v in names.items() if v and v.lower() == pattern}
    if exact:
        return exact
    inside = f"*{pattern}*"
    return {k for k, v in names.items()
            if fnmatch.fnmatchcase(k.lower(), inside) or (v and fnmatch.fnmatchcase(v.lower(), inside))}


def select(filters):
    """The rows the filters pick, in filter order and without repeats, and the filters that picked nothing."""
    picked, unmatched = {}, []
    creature_names = {c: DROPS[c][0] for c in DROPS}
    for text in filters:
        creature_pat, levels, item_pat, either = parse_filter(text)
        creatures, items = matching(creature_pat, creature_names), matching(item_pat, ITEM_NAMES)
        found = False
        for row in rows_at(levels):
            if (row.creature in creatures or row.item in items) if either else \
                    (row.creature in creatures and row.item in items):
                picked.setdefault((row.creature, row.stars, row.item, row.chance), row)
                found = True
        if not found:
            unmatched.append(text)
    return list(picked.values()), unmatched


# ---------------------------------------------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------------------------------------------

def percent(p):
    # stars can take a chance past 1 (a 50% drop at 2 stars is 2.0); the game then drops it every time
    return f"{min(p, 1) * 100:.2f}".rstrip("0").rstrip(".") + "%"


def rule(row):
    if row.chance >= 1:
        return "always"
    if row.chance <= 0:
        return "never"
    return "counter" if row.key is not None else "roll"


def next_drop(row, counters):
    if row.key is None:
        return "every kill" if row.chance >= 1 else "-"
    if row.key not in counters:
        return f"not started (within {first_drop_within(row.chance)} kills)"
    n = max(counters[row.key], 1)
    return "next kill" if n == 1 else f"in {n} kills"


def sharing(row, index):
    """The other creatures that use this row's counter: Creature.N, or Creature.* when the drop ignores stars."""
    names = []
    for other in index.get(row.key, []):
        if other.creature == row.creature:
            continue
        name = f"{other.creature}.*" if not other.scales else f"{other.creature}.{other.stars}"
        if name not in names:
            names.append(name)
    return names


def shared_with(row, index, verbose):
    names = sharing(row, index)
    if not verbose and len(names) > SHARED_SHOWN:
        return ", ".join(names[:SHARED_SHOWN]) + f" +{len(names) - SHARED_SHOWN} more"
    return ", ".join(names)


def print_table(rows, counters, index, verbose):
    head = ["drop", "chance", "rule"] + (["next drop"] if counters is not None else []) + ["longest gap", "shared with"]
    lines = []
    for row in rows:
        gap = str(first_drop_within(row.chance) + 1) if row.key is not None else "-"
        cells = [label(row), percent(row.chance), rule(row)]
        if counters is not None:
            cells.append(next_drop(row, counters))
        lines.append(cells + [gap, shared_with(row, index, verbose) if row.key is not None else ""])
    widths = [max(len(x[i]) for x in [head] + lines) for i in range(len(head))]
    right = {1, len(head) - 2}                  # chance and longest gap are numbers
    for cells in [head] + lines:
        print("  ".join(c.rjust(w) if i in right else c.ljust(w) for i, (c, w) in enumerate(zip(cells, widths))).rstrip())


def saved_rows(counters, index):
    """One row per saved counter, and the keys no drop uses.

    The row is the counter's most typical user (a drop that scales with stars, then the shortest creature name: Goblin
    rather than DvergerTest); the other users are listed as sharing it."""
    rows, unknown = [], []
    fallback = None
    for key in counters:
        users = index.get(key)
        if not users:
            # not a drop at 0-2 stars: try the rarer 3 and 4 star creatures before giving up
            fallback = fallback or by_counter(rows_at((3, 4)))
            users = fallback.get(key)
        if users:
            rows.append(min(users, key=lambda r: (not r.scales, len(r.creature), r.creature, r.stars)))
        else:
            unknown.append(key)
    rows.sort(key=lambda r: (r.item.lower(), r.chance, r.creature))
    return rows, unknown


# ---------------------------------------------------------------------------------------------------------------
# The web page (web/drops-worker.js runs this script with Pyodide)
# ---------------------------------------------------------------------------------------------------------------

def split_filters(text):
    """The filters in the page's text box. They are separated by commas or new lines, or by spaces when every part has
    a dot: 'Greydwarf.TrophyGreydwarf Wolf.TrophyWolf' is two filters, 'Greydwarf.Greydwarf trophy' is one."""
    out = []
    for part in re.split(r"[,;\n]+", text or ""):
        words = part.split()
        if len(words) > 1 and all("." in w for w in words):
            out += words
        elif words:
            out.append(" ".join(words))
    return out


def row_json(row, counters, index):
    out = {"drop": label(row), "creature": row.creature, "creatureName": DROPS[row.creature][0], "stars": row.stars,
           "item": row.item, "itemName": ITEM_NAMES.get(row.item, row.item), "chance": min(row.chance, 1),
           "rule": rule(row)}
    if row.key is not None:
        out["within"] = first_drop_within(row.chance)
        out["longestGap"] = out["within"] + 1
        out["shared"] = sharing(row, index)
        if counters is not None:
            saved = counters.get(row.key)
            out["next"] = None if saved is None else max(saved, 1)    # None: not started yet
    return out


def web_drops(filters="", data=None):
    """JSON for the web page: the rows the filters pick, or every counter saved in the character when there is no
    filter. `data` is the save's bytes (a Uint8Array from the page, or bytes), or None to show only the rules."""
    try:
        wanted = split_filters(filters)
        rows, unmatched = select(wanted)
        name = counters = None
        if data is not None:
            name, counters = load(bytes(data.to_py()) if hasattr(data, "to_py") else bytes(data))
    except (SaveError, ValueError) as e:
        return json.dumps({"error": str(e)})
    index = by_counter(rows_at(sorted(set(STARS) | {row.stars for row in rows})))
    unknown = []
    if counters is not None and not wanted:
        rows, unknown = saved_rows(counters, index)
    return json.dumps({"character": name, "saved": None if counters is None else len(counters), "filtered": bool(wanted),
                       "unmatched": unmatched, "rows": [row_json(r, counters, index) for r in rows],
                       "unknown": [[k, counters[k]] for k in unknown]})


def main():
    ap = argparse.ArgumentParser(description="How far a character is from each rare creature drop in Valheim.",
                                 epilog="A filter is creature.item (at 0, 1 and 2 stars), creature.N.item (at N stars), "
                                 "creature.N or a single word (the creature or the item). A part of a prefab or display "
                                 "name is enough (greyd.troph, trophy); a full name matches just that one. An empty "
                                 "part or * is anything (.coins). Without a filter, every counter saved in the "
                                 "character is shown.")
    ap.add_argument("inputs", nargs="+", metavar="save.fch|filter", help=".fch character files and drop filters")
    ap.add_argument("-v", "--verbose", action="store_true", help="name every creature that shares a counter")
    args = ap.parse_args()
    saves = [x for x in args.inputs if x.lower().endswith(".fch") or os.path.isfile(x)]
    filters = [x for x in args.inputs if x not in saves]
    try:
        rows, unmatched = select(filters)
    except ValueError as e:
        ap.error(str(e))
    status = 0

    def fail(message):
        nonlocal status
        sys.stdout.flush()
        print(message, file=sys.stderr)
        status = 1

    for text in unmatched:
        fail(f"no drop matches {text!r}")
    levels = sorted(set(STARS) | {row.stars for row in rows})
    index = by_counter(rows_at(levels))
    if not saves:
        if rows:
            print_table(rows, None, index, args.verbose)
        return status
    printed = counted = False
    for path in saves:
        try:
            name, counters = load(path)
        except (OSError, SaveError) as e:
            fail(f"{path}: {e}")
            continue
        if printed:
            print()
        printed = True
        print(f"{name} ({os.path.basename(path)}): {len(counters)} drop counters saved")
        shown, unknown = (rows, []) if filters else saved_rows(counters, index)
        if shown:
            print()
            print_table(shown, counters, index, args.verbose)
        if unknown:
            print(f"\n{len(unknown)} saved counters match no drop in the table (a newer game version or a mod?): "
                  + ", ".join(f"{k}={counters[k]}" for k in unknown))
        counted |= any(row.key is not None for row in shown)
    if counted:
        print("\n'in N kills': the N-th kill from now drops it. Only kills of creatures your game owns count; in "
              "multiplayer the owner is usually whoever reached the area first.")
    return status


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BrokenPipeError:             # the output went into something like head, which stopped reading
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        sys.exit(1)
