# Game data tables

Generated from the installed game (Valheim 1.0.16, Deep North included) by `tools/extract_game_data.py`. Nothing here comes from a wiki.

| File | What it is |
|---|---|
| `recipes.csv` / `.json` | Every crafting recipe, build piece and processing recipe, with ingredients, station and the biome you need to reach. |
| `gatherables.csv` / `.json` | Every item that can be found in the world, with the earliest biome and where it comes from. |
| `craftable_biomes.csv` / `.json` | **For every craftable item and build piece: the earliest biome in which it can be made**, what holds it back, and why when it cannot be worked out. |
| `biomes.json` | The earliest biome of every craftable item, build piece, gatherable item and creature; this is what `tools/update_script_biomes.py` copies into `achi_hunter.py`. |
| `unsourced_items.csv` | Materials, food, trophies and fish that are neither craftable nor found by the rules below (mostly Deep North loot and moulds). |

## craftable_biomes

One row per thing you can make (items, build pieces, smelted and cooked items, fermented meads, farmed crops). Where an output has several recipes, the cheapest one is used (`other_recipes` says how many more exist).

- `earliest_biome`: the furthest biome you must reach to have everything: every ingredient (gathered, traded or crafted from its own ingredients) and the crafting station, at the station level the recipe needs. Recipes that accept "any one" of several ingredients use the earliest of them.
- `limited_by`: the ingredient(s) or station that set that biome.
- `earliest_biome_direct`: the same, but without loot (chests, dungeons), offerings and boss drops. It can be later than `earliest_biome`, or blank.
- `blocked_by`: set when `earliest_biome` is blank: the ingredient or station that has no source in the game data.
- `earliest_biome_inferred`, `inferred_from`, `still_blocked_by`: for rows that were blocked. **At the moment every row has a firm answer, so these columns are empty and `inferred_items.csv` has no rows**; the mechanism stays in case a game update adds items with no source. Deep North is only partly wired into world generation in this game version (gold ore, Frostfire essence and the Nord moulds exist as prefabs but no location or spawner places them). Items whose only producers are Deep North prefabs are assumed to come from Deep North. `inferred_from` names those items. If `still_blocked_by` is filled, even that did not help.

Station levels: a station of level L needs L-1 extensions (each extension type once, unless it stacks), and an extension is a piece with its own ingredients, so upgrading a Forge or Workbench can push a recipe to a later biome than its ingredients do.

Farming: planting a seed with the Cultivator turns it into its crop, which is available once the seed and the Cultivator are, in a biome where the plant can grow. Crops are listed with `kind` = `farming`.

Traders: items sold by Haldor, Hildir and the Bog Witch count, in the biome of their camp. When a trader only sells an item after a boss is defeated (the game's "global key"), the item counts from that boss's biome instead (for example Haldor's Egg needs Yagluth, so chickens are a Plains thing).

Hatching and structures: an egg hatches into a creature, whose drops then become available (Chicken Meat). Wisp and Embers only exist once a structure is built (the Wisplight and the Fader ember structure), so they are as early as that structure.

### Rules that are not in the game files

These are stated assumptions, kept together at the top of `tools/derive.py` (`MANUAL_PLACEMENT`, `ITEM_FROM_STRUCTURE`, `MANUAL_ITEM_BIOME`, `KEY_BIOME`) so they are easy to change:

- The Bog Witch's camp is not in any location list, so the Swamp is assumed for her.
- The "Hole" caves (generators `DG_Hole`, `TheHole01`) are not in any location list either. Their entrances (`StumpHole`) are in the Deep North vegetation, so Deep North is assumed. This is where Luminous Larva and Frostcore come from.
- Wisp comes from the Wisplight structure, Embers from the Fader ember structure, and Sap from the sap extractor, which has to stand on a Yggdrasil root (Mistlands).
- Fish bonus items (the ore, seeds and so on some fish carry in the game files) are never counted toward a biome. Onion Seeds, for example, are Mountain chest loot, not Ocean.
- Fenris Claw is a Mountain dungeon drop. Sealbreaker fragments are treated as available in Mistlands.
- Every mould is a Deep North item (dungeons and mobs). Jotun Witches (Hexen), Jotun Warriors (Krigen) and Frost Blobs only spawn in Deep North, so their drops are Deep North. The Ancient Coin and the four ancient gemstones (Draumyx, Grimvarn, Solryth, Veydris) are Deep North dungeon loot; the gemstones are assumed to share the coin's chests.
- Frostfire and Thunderblood Essence come from sacrificing Memorial Coal, so they are Deep North. Oat Seeds and Seed Poteitr grow in the North villages (Deep North). The Frozen King is Deep North's last boss, so his drops (Crown Jewel, Sacrificial Blood) are Deep North. Mork blobs live in Deep North dungeons. The Salvaged Lantern drops from destroying a Standing Lantern, a very rare structure that can appear in Meadows at the earliest, so it counts as Meadows.
- Petrified Tissue (the gold ore item, smelted into Bloodgold at the Blast Furnace) is mined from the corpse of a Gammeltroll in Deep North. The corpse's location is not placed in the data, so this is stated by hand.
- Each boss key maps to the biome of that boss (Eikthyr Meadows, the Elder Black Forest, Bonemass Swamp, Moder Mountain, Yagluth Plains, the Queen Mistlands, Fader Ashlands, the Frozen King Deep North). Hildir's quest keys map to the biome of his miniboss: Brenna (Black Forest), Geirrhafa (Mountain), Zil & Thungr (Plains). Hildir himself is in Meadows.
- Zil is spawned by code together with Thungr in the Plains fortress, and the Frozen King's arena (`DN_Bossroom`) is in no location list, so they are placed by hand in Plains and Deep North.
- Spawns that only happen during the Fimbulvinter event (Elakingar, Jotun warriors and witches, meteors) are not counted as normal world spawns.

## recipes

`kind` is one of: `item` (crafted at a station or by hand), `piece` (built with a hammer, hoe or cultivator), `smelting` (smelter, blast furnace, kiln, windmill, spinning wheel), `cooking` (fire, oven, griddle), `fermenting` (mead kettle) or `farming` (a planted seed and the crop it grows).

- `ingredients`: `Name xN`. `(+M/upgrade level)` is the extra amount per upgrade level, shown only for equipment that can be upgraded.
- `any_one_ingredient`: the game accepts any one of the listed ingredients.
- `biome_needed`, `biome_needed_direct`, `biome_needed_inferred`: the same three numbers as in `craftable_biomes.csv`, but for this one recipe (not the cheapest recipe of the output).
- `enabled`: `False` for recipes that exist in the game files but are switched off (seasonal and unused items).

## gatherables

- `earliest_biome`: the earliest biome in which the item can be obtained by any means below.
- `earliest_biome_direct`: the same, but ignoring loot (chests, dungeons), offerings and boss drops. Blank when the item only comes from those.
- `found_via`: `pickable` (bushes, mushrooms, ...), `tree`, `mining`, `destructible` (breakables and rocks), `creature`, `fishing` (the fish itself), `fishing bonus` (ore, seeds, ... carried by some fish; listed for information only, it never decides a biome), `loot`, `boss`.
- `earliest_by_source`: the earliest biome for each way of getting it.

Biome order used: Meadows, Black Forest, **Ocean**, Swamp, Mountain, Plains, Mistlands, Ashlands, Deep North. A Raft can technically leave Meadows, but the open Ocean is not viable without Bronze, so the Ocean is a step after the Black Forest and before the Swamp. Ocean-only items show `Ocean`.

Rules:

- Spawns that require a defeated boss (the game's "global key") are ignored.
- Boss drops are listed with the biome of the boss altar and count only toward `earliest_biome`. Items sold by traders are listed in the recipe tables but are not "gatherable".
- Dungeons (crypts, caves, ...) are filled with their rooms by theme, so crypt loot is attributed to the biome of the crypt.

## Regenerating

```bash
pip install UnityPy
python3 tools/extract_game_data.py --game "<path to steamapps/common/Valheim>" --out data
```

It scans about 800 asset bundles in a few minutes and keeps the raw scan in `data/raw.json` (git-ignored) so the tables can be rebuilt in seconds with `--raw data/raw.json`.

It also writes `biomes.json` (the earliest biome of every token). To copy those into the script, run:

```bash
python3 tools/update_script_biomes.py
```

That rewrites the generated `BIOME_*` block in `achi_hunter.py`, which is how the script and the web page know the biome of each item, piece, creature, trophy and fish.
