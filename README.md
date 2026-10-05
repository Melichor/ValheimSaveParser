# ValheimSaveParser (achi_hunter)

A small command-line tool that reads a Valheim character file (`.fch`) and tells you **what you are still missing for the achievements**: items to craft, pieces to build, creatures and bosses to kill, ways to die, trophies, fish.

It is a single Python file with no dependencies (Python 3, standard library only).

```
python3 achi_hunter.py path/to/Character.fch
```

## Quick start

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
  [ ] EdgeOfWorld
  [ ] Freezing
  [ ] Poisoned
  [ ] Smoke

== Bosses killed (Hard): 1 / 8 ==
  [ ] bonemass
  [ ] dragon
  ...
```

## Options

| Option | Meaning |
|---|---|
| `save` | Path to the `.fch` file (required). |
| `-f`, `--full` | Also list completed entries (`[x]`, with counts), not just the missing ones (`[ ]`). |
| `-o LIST`, `--only LIST` | Show only these lists. Comma-separated, or repeat the option. |
| `-h`, `--help` | Show help. |

By default every list is shown, and only the missing entries are printed (each list still shows `done / total` in its heading).

## Lists

| `-o` name | Achievement it tracks | Counted from |
|---|---|---|
| `crafted` | Craft every item (recipes that need a crafting station) | Any difficulty |
| `weapons` | Craft every weapon | Any difficulty |
| `cooked` | Cook / craft every food | Any difficulty |
| `built` | Build every piece in the Hammer menu | Any difficulty |
| `deaths` | Die in every way (enemy, fall, drowning, burning, freezing, poison, smoke, edge of the world) | Any difficulty |
| `tree-deaths` | Be killed by each of the 8 tree varieties | Any difficulty |
| `enemies` | Kill every creature | Any difficulty |
| `enemies-hard` | Kill every creature on Hard | Hard |
| `bosses` | Kill every boss | Normal or higher |
| `bosses-hard` | Kill every boss on Hard | Hard |
| `minibosses` | Kill every mini-boss | Any difficulty |
| `fishing` | Catch every fish species | Any difficulty |
| `trophies` | Collect every trophy | Any difficulty |

## Where is my save file?

Valheim keeps character files in a `characters_local` folder (or `characters` when Steam Cloud is used):

- **Linux:** `~/.config/unity3d/IronGate/Valheim/`
- **Windows:** `%USERPROFILE%\AppData\LocalLow\IronGate\Valheim\`

The tool only reads the file; it never writes to it. Copy it somewhere first if you want to be extra careful.

## How it works

The list of what each achievement needs was **not guessed from wikis**. It was rebuilt from the game's own data and code (Valheim 1.0.16): the achievement definitions, the item database, recipes, build tables and character flags. The game fills most of these lists when it starts, and the tool reproduces the same rules, including the game's hand-maintained exclusions. That is why, for example:

- hand-crafted recipes with no station (stone axe, club, ...) do **not** count towards "craft everything" but **do** count towards "craft every weapon";
- Cultivator and Hoe pieces do not count towards "build everything";
- a trophy only counts once it has been **picked up** after achievement tracking started;
- a fish only counts when it is **reeled in**, not when you pick it up from the ground.

The save stores ten sets of statistics, one per difficulty (`RawStats`, `Any`, `Hammer`, `Casual`, `VeryEasy`, `Easy`, `Default`, `Hard`, `VeryHard`, `Hardcore`). Achievements read the set that matches their difficulty requirement and never the raw one, so the numbers can be lower than what the in-game stats screen suggests (cheated or pre-tracking activity only lives in the raw set). The file layout is documented at the top of `achi_hunter.py`.

## Limitations

- Written for **profile version 46** saves from **Valheim 1.0.16**. A game update may add items, pieces or creatures; the lists near the top of the script are plain Python lists and need regenerating after an update. Saves from other profile versions are not checked and may fail with an error or give wrong results.
- Names are shown as the game's internal names (for example `charred_melee_Dyrnwyn`, `item_trophy_boar`) without the `$item_` / `$enemy_` prefixes.
- The in-game achievement list can differ slightly if the game build you play has a different item set (for example a modded game).
