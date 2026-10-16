# ValheimSaveParser (achi_hunter)

A small command-line tool that reads a Valheim character file (`.fch`) and tells you **what you are still missing for the achievements**: items to craft, pieces to build, creatures and bosses to kill, ways to die, trophies, fish.

It is a single Python file with no dependencies (Python 3, standard library only).

```
python3 achi_hunter.py path/to/Character.fch
```

## Web version

You can visit the web version here: [https://melichor.github.io/ValheimSaveParser/index.html](https://melichor.github.io/ValheimSaveParser/index.html)

It has an **"I'm currently in"** dropdown (default: Deep North). Pick a biome and every list only shows the items you are missing that can be done up to that biome; each item shows its earliest biome.

## Upgrade predictor

`upgrade_oracle.py` (also a single file, standard library only) predicts how many times an item can be upgraded at the Forge of Potential before it breaks. A character's first attempt on each item and level is a fixed roll that depends only on the character's name, and the script replays it. It can also search for character names that give 8 upgrades in a row (the most a new character can get):

```bash
python3 upgrade_oracle.py Character.fch                       # the upgradable items in the inventory
python3 upgrade_oracle.py Character.fch --charname Ragnar     # the same items for a new character with another name
python3 upgrade_oracle.py --item 'Staff of Protection' --quality 4 --findnameperupgr 8   # names, no save needed
python3 upgrade_oracle.py --item 'Staff of Protection' --quality 4 --findnameperupgr 8 --copies 2   # slow: a second copy must get past the break
```

`--copies N` upgrades N copies of the item one after another with the same character: the first N-1 get exactly the wanted upgrades and break, and the last one gets past the level where they broke. Names like that are rare (about 1 in 10 million for 8 upgrades and 2 copies), so the search takes minutes.

The web page has the same name search under **Upgrade name finder**: enter the item and its starting quality. Under it, the **Relay planner** finds a chain of new characters that takes an item from its current quality to a target quality without breaking it: each character makes only the upgrades its own rolls get right, then hands the item on. At the bottom of the page, the **Upgrade predictor** takes a dropped character file and shows what the script prints for it: every upgradable item in the inventory, how many upgrades it can take before it breaks, and the path. The game keeps the case of the name you type, so type the names exactly as listed.

## Game data tables

`data/` holds tables extracted from the game files: every recipe (`recipes.csv`) and every item that can be found in the world with the earliest biome it appears in (`gatherables.csv`), plus the earliest biome in which each craftable item can be made (`craftable_biomes.csv`). See [`data/README.md`](data/README.md) for the columns and the rules, and `tools/extract_game_data.py` to regenerate them.

## Quick start

You can download just the `achi_hunter.py` no other file is needed for this.

```bash
# everything you're still missing, for all lists
python3 achi_hunter.py MyCharacter.fch

# also show what you've already done, with counts
python3 achi_hunter.py MyCharacter.fch --full

# only some lists
python3 achi_hunter.py MyCharacter.fch -o bosses,trophies
python3 achi_hunter.py MyCharacter.fch -o fishing -o minibosses
```

Example output:

```
MyCharacter.fch: profile v46, worlds: Home, Hard

== Ways to die: 3 / 8 ==
  [ ] Drowning
  [ ] Edge of the world
  [ ] Freezing
  [ ] Poisoned
  [ ] Smoke

== Bosses killed (Hard): 1 / 8 ==
  [ ] gdking                                 Black Forest
  [ ] bonemass                               Swamp
  [ ] dragon                                 Mountain
  ...
```

## Options

| Option | Meaning |
|---|---|
| `save` | Path to the `.fch` file (required). |
| `-f`, `--full` | Also list completed entries (`[x]`, with counts), not just the missing ones (`[ ]`). |
| `-o LIST`, `--only LIST` | Show only these lists. Comma-separated, or repeat the option. |
| `--json` | Print the result as JSON (every entry of the chosen lists, with its count and earliest biome) instead of text. This is what the web page uses. |
| `-h`, `--help` | Show help. |

By default every list is shown, and only the missing entries are printed (each list still shows `done / total` in its heading). Next to each entry is the earliest biome in which it can be done. The biome order is Meadows, Black Forest, Ocean, Swamp, Mountain, Plains, Mistlands, Ashlands, Deep North. The biomes for the ways to die and the tree deaths are stated by hand in the script (`DEATH_BIOME`, `TREE_BIOME`); all other biomes come from the game data.

## Lists

| `-o` name | Achievement it tracks | Counted from |
|---|---|---|
| `crafted` | Craft every item (recipes that need a crafting station) | Any difficulty |
| `weapons` | Craft every weapon | Any difficulty |
| `cooked` | Cook / craft every food | Any difficulty |
| `food-eaten` | **The Gourmet**: eat every food once (raw and cooked versions are separate foods) | Any difficulty |
| `built` | Build every piece in the Hammer menu | Any difficulty |
| `deaths` | Die in every way (16 kinds: enemy, fall, drowning, burning, freezing, poison, smoke, edge of the world, tree, turret, stalactite, catapult, Ashlands ocean, obliterator, drawbridge, Ashlands lava) | Any difficulty |
| `tree-deaths` | Be killed by each of the 10 tree varieties | Any difficulty |
| `enemies` | Kill every creature | Any difficulty |
| `enemies-hard` | Kill every creature on Hard | Hard |
| `bosses-any` | Kill every boss | Any difficulty |
| `bosses-normal` | Kill every boss on Normal or harder (`bosses` still works as a short name) | Normal or higher |
| `bosses-hard` | Kill every boss on Hard | Hard |
| `minibosses` | Kill every mini-boss | Any difficulty |
| `fishing` | Catch every fish species | Any difficulty |
| `trophies` | Collect every trophy | Any difficulty |

## Where is my save file?

**Local saves** (Steam Cloud off) are in a `characters_local` folder:

- **Windows:** `%USERPROFILE%\AppData\LocalLow\IronGate\Valheim\characters_local`
- **Linux:** `~/.config/unity3d/IronGate/Valheim/characters_local`

**Steam Cloud saves** are not in the game's own folder. Steam keeps them in its `userdata` folder:

```
<Steam folder>/userdata/<your Steam ID number>/892970/remote/characters
```

- `<Steam folder>` is `C:\Program Files (x86)\Steam` on Windows, and `~/.steam/steam` or `~/.local/share/Steam` on Linux and Steam Deck (some distros, e.g. Debian, use `~/.steam/debian-installation`).
- `<your Steam ID number>` is the numeric folder inside `userdata`. If there are several, open the one that was modified most recently.
- `892970` is Valheim's Steam app id.
- Shortcut: in Steam, right-click Valheim → **Manage → Browse local files**. That opens `.../Steam/steamapps/common/Valheim`; go up three folders to reach the Steam folder, then follow the path above.
- Tip: once you are in the `userdata` folder, search it for your character's name or for `892970`. That finds the right folder and file straight away.

The file is named after your character (e.g. `Ragnar.fch`). Next to it you may see `.fch.old` files and `..._backup_...fch` copies; use the plain `.fch` file for the current state of the character.

The tool only reads the file; it never writes to it. Copy it somewhere first if you want to be extra careful.

## How it works

The list of what each achievement needs was **not guessed from wikis**. It was rebuilt from the game's own data and code (Valheim 1.0.16): the achievement definitions, the item database, recipes, build tables and character flags. The game fills most of these lists when it starts, and the tool reproduces the same rules, including the game's hand-maintained exclusions. That is why, for example:

- hand-crafted recipes with no station (stone axe, club, ...) do **not** count towards "craft everything" but **do** count towards "craft every weapon";
- Cultivator and Hoe pieces do not count towards "build everything";
- a trophy only counts once it has been **picked up** after achievement tracking started;
- a fish only counts when it is **reeled in**, not when you pick it up from the ground.

The save stores ten sets of statistics, one per difficulty (`RawStats`, `Any`, `Hammer`, `Casual`, `VeryEasy`, `Easy`, `Default`, `Hard`, `VeryHard`, `Hardcore`). Achievements read the set that matches their difficulty requirement and never the raw one, so the numbers can be lower than what the in-game stats screen suggests (cheated or pre-tracking activity only lives in the raw set). The file layout is documented at the top of `achi_hunter.py`.

## Limitations

- Written for **profile version 46** saves from **Valheim 1.0.16**; version 47 is tested too, and newer versions are read with a warning. A game update may add items, pieces or creatures; the lists near the top of the script are plain Python dictionaries (token to display name) and need regenerating after an update. Older versions, or a save whose stat count differs from what the script expects (a sign that the game changed its stats list), are rejected with an error message.
- The terminal output shows the game's internal names (for example `charred_melee_Dyrnwyn`, `trophy_boar`) without the `$item_` / `$enemy_` prefixes; the web page and `--json` also carry display names where the game has one.
- The in-game achievement list can differ slightly if the game build you play has a different item set (for example a modded game).
