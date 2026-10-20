#!/usr/bin/env python3
"""How hard is it, the honest way, to get an item to a high quality at the Forge of Potential?

Generates random character names and, for each, replays exactly what upgrade_cost.py does: craft a copy, take it to its
station's cap, then try the Forge until it breaks, crafting the next copy, until one copy reaches the target. It
records how many copies (and Idols) each name needed before a copy first reached each level, and summarises that over
all names, next to what plain 65% odds would predict.

    python3 tools/upgrade_odds.py                              # 1000 names, Iron Sword, levels 10 15 20 25
    python3 tools/upgrade_odds.py --names 200 --item "Fenris Hood" --levels 8 12 16
    python3 tools/upgrade_odds.py --seed 7                     # a different (but repeatable) set of names

Each name is a new character (no saved seeds), so its first attempt at every level comes from the name and every later
attempt from the seed the game stored after the one before. One run up to the highest level answers all the lower
ones too: the copies made before one first reaches a level are the same as in a separate run to that level.
"""
import argparse
import random
import statistics
import string
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import upgrade_cost as cost  # noqa: E402
import upgrade_oracle as oracle  # noqa: E402

MAX_COPIES = 2_000_000          # per name; a name that needs more is reported as not reached


def random_name(rng, min_len=3, max_len=12):
    """A name a player could type: ASCII letters, upper and lower case."""
    return "".join(rng.choice(string.ascii_letters) for _ in range(rng.randint(min_len, max_len)))


def run(prefab, start, levels, name, max_copies=MAX_COPIES):
    """Replay one new character upgrading copies from `start` until a copy reaches max(levels).

    Returns {level: (copies needed, Forge attempts used)} for each level reached (the attempts are the Idols)."""
    top = max(levels)
    base, name_hash = oracle.stable_hash(prefab), oracle.stable_hash(name)
    seeds, found = {}, {}
    copies = attempts = 0
    while copies < max_copies:
        copies += 1
        level = start
        while level < top:
            to = level + 1
            key = (base + to) & oracle.M32
            seed = seeds[key] if key in seeds else (name_hash + key) & oracle.M32
            value, seeds[key] = oracle.fast_roll(seed)
            attempts += 1
            if value > oracle.UPGRADE_CHANCE:
                break                           # the item breaks (BREAK_CHANCE is 1.0: every failure breaks it)
            level = to
            if level in levels and level not in found:
                found[level] = (copies, attempts)
        if level >= top:
            break
    return found


def pct(values, q):
    """The q-th percentile (0..100) of a sorted list."""
    return values[min(len(values) - 1, int(q / 100 * len(values)))]


def main():
    ap = argparse.ArgumentParser(description="Upgrade odds over many random character names, without name tricks.")
    ap.add_argument("--names", type=int, default=1000, help="how many random names to try (default: 1000)")
    ap.add_argument("--item", default="Iron Sword", help="the item (default: Iron Sword)")
    ap.add_argument("--levels", type=int, nargs="+", default=[10, 15, 20, 25], help="target qualities (default: 10 15 20 25)")
    ap.add_argument("--seed", type=int, default=1, help="seed for picking the random names, so a run can be repeated")
    args = ap.parse_args()
    if oracle.BREAK_CHANCE < 1.0:
        sys.exit("this script assumes every failed attempt breaks the item (BREAK_CHANCE 1.0)")
    try:
        prefab = cost.find(args.item)
    except oracle.SaveError as e:
        sys.exit(str(e))
    info = cost.ITEMS[prefab]
    start = info["cap"]
    levels = sorted({lv for lv in args.levels if lv > start})
    if not levels:
        sys.exit(f"every level is at or below {start}, where {info['name']} gets without the Forge of Potential")
    rng = random.Random(args.seed)
    names = [random_name(rng) for _ in range(args.names)]

    results, t0 = [], time.time()
    for i, name in enumerate(names, 1):
        results.append(run(prefab, start, set(levels), name))
        if i % 50 == 0 or i == len(names):
            print(f"\r  {i}/{len(names)} names, {time.time() - t0:.0f} s", end="", file=sys.stderr, flush=True)
    print(file=sys.stderr)

    p = oracle.UPGRADE_CHANCE
    print(f"{info['name']}: each copy starts at quality {start} (its station's cap), {len(names):,} random new characters")
    print(f"Plain 65% odds: a copy reaches level L with chance 0.65^(L - {start}), "
          "so it takes 1 / that many copies on average.\n")
    head = (f"{'Level':>5}  {'1st copy makes it':>17}  {'median copies':>13}  {'mean copies':>11}  {'90% need ≤':>10}  "
            f"{'worst':>9}  {'mean Idols':>10}  {'65% odds: copies':>16}")
    print(head)
    print("-" * len(head))
    for lv in levels:
        got = [r[lv] for r in results if lv in r]
        copies = sorted(c for c, _ in got)
        idols = [a for _, a in got]
        first = sum(1 for c in copies if c == 1) / len(names)
        expect = 1 / p ** (lv - start)
        missing = len(names) - len(got)
        if not got:
            print(f"{lv:>5}  {'none of the names got there':>60}")
            continue
        print(f"{lv:>5}  {first:>16.1%}  {statistics.median(copies):>13,.0f}  {statistics.mean(copies):>11,.0f}  "
              f"{pct(copies, 90):>10,}  {copies[-1]:>9,}  {statistics.mean(idols):>10,.0f}  {expect:>16,.0f}"
              + (f"   ({missing} names not there after {MAX_COPIES:,} copies)" if missing else ""))
    print("\n1st copy makes it: share of names whose very first copy reaches the level. A new character's first rolls")
    print(f"come from its name, and those can never give more than {oracle.MAX_FIRST_RUN} upgrades in a row, so above "
          f"level {start + oracle.MAX_FIRST_RUN} the first copy never makes it.")


if __name__ == "__main__":
    main()
