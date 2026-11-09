#!/usr/bin/env python3
"""Seeded choice of base outputs and slots for the 40 validation items. Writes construction/plan.json only.
Read-only on ../pipeline/runs and the registry. Deterministic for a given seed."""
import json
import os
import random
import sys

import vlib
from vlib import (COMPOSITION, HERE, ROOT, SEED, exact_hit, family_of, key_hits, load_pool, parse_near_misses,
                  read_jsonl)

PLAN = os.path.join(HERE, "construction", "plan.json")


def pick_area_rows(rng, area):
    fams = {}
    while True:
        pick = rng.sample(area, 4)
        fams = {family_of(r["id"]) for r in pick}
        if {"P1", "P2"} <= fams:
            return pick


def pick_multi(rng, registry):
    """Two items, two rows each: different reach tier and different registry type inside an item,
    and no row shared between the two items."""
    for _ in range(10000):
        rows = rng.sample(registry, 4)
        pairs = [rows[:2], rows[2:]]
        if all(a["type"] != b["type"] and a["intended_reach"] != b["intended_reach"] for a, b in pairs):
            return pairs
    raise SystemExit("no multi-row pairing found")


def penalty(base, rows, pm):
    """Soft topic preference: 0 when the probe has nothing to do with the inserted row."""
    p = pm[base["probe_id"]]
    pen = 0
    for r in rows:
        fam = family_of(r["id"])
        if fam and fam.replace("P", "P") in p["carries"]:
            pen += 2
        if r["id"] in p["tempts"] or r["id"] in p["allowed"]:
            pen += 1
    return pen


def usable(base, rows):
    return not any(exact_hit(base["text"], r) or key_hits(base["text"], r) for r in rows)


def assign(pool, slots, pm, rng_seed):
    for attempt in range(5000):
        rng = random.Random("%s|assign|%d" % (rng_seed, attempt))
        kept = sorted(rng.sample(pool, 40), key=lambda b: (b["run_id"], b["probe_id"]))
        clean = [b for b in kept if not any(exact_hit(b["text"], r) for r in REGISTRY)]
        clean_slots = [s for s in slots if s["kind"] in ("near_miss", "none")]
        row_slots = [s for s in slots if s["kind"] not in ("near_miss", "none")]
        if len(clean) < len(clean_slots):
            continue
        chosen = rng.sample(clean, len(clean_slots))
        got = {}
        for s, b in zip(clean_slots, chosen):
            got[s["slot"]] = b
        left = [b for b in kept if b not in chosen]
        order = row_slots[:]
        rng.shuffle(order)
        ok = True
        for s in order:
            rows = [REG[r] for r in s["rows"]]
            cands = [b for b in left if usable(b, rows)]
            if not cands:
                ok = False
                break
            rng.shuffle(cands)
            b = min(cands, key=lambda b: penalty(b, rows, pm))
            got[s["slot"]] = b
            left.remove(b)
        if ok:
            return got, attempt, [b for b in pool if b not in kept]
    raise SystemExit("could not assign bases under the constraints")


def main():
    global REGISTRY, REG
    REGISTRY = read_jsonl(os.path.join(ROOT, "registry.jsonl"))
    REG = {r["id"]: r for r in REGISTRY}
    pm = {r["id"]: r for r in read_jsonl(os.path.join(ROOT, "probe_map.jsonl"))}
    pool = load_pool()
    if len(pool) != 42:
        raise SystemExit("expected 42 usable bases, found %d" % len(pool))
    rng = random.Random("%d|slots" % SEED)
    by_type = {}
    for r in REGISTRY:
        by_type.setdefault(r["type"], []).append(r)
    area = pick_area_rows(rng, by_type["area_pattern"])
    multi = pick_multi(rng, REGISTRY)
    near = parse_near_misses(open(os.path.join(ROOT, "near_misses.md"), encoding="utf-8").read())
    sections = []
    for q in near:
        if q["section"] not in sections:
            sections.append(q["section"])
    nm = [rng.choice([q for q in near if q["section"] == s]) for s in sections]
    literal = set(rng.sample(range(len(nm)), 3))
    slots = []

    def add(kind, rows, **kw):
        slots.append(dict(slot="S%02d" % (len(slots) + 1), kind=kind, rows=[r["id"] for r in rows],
                          seeds=[rng.randrange(2 ** 31) for _ in range(max(1, len(rows)))], **kw))
    for r in by_type["verbatim"]:
        add("verbatim", [r])
    for r in by_type["paraphrase"]:
        add("paraphrase", [r])
    for r in by_type["client_pattern"]:
        add("client_pattern", [r])
    for r in area:
        add("area_pattern", [r])
    for pair in multi:
        add("multi", pair)
    for i, q in enumerate(nm):
        add("near_miss", [], near_miss=dict(q, mode="literal" if i in literal else "reworded"))
    for _ in range(4):
        add("none", [])
    assert [(k, sum(1 for s in slots if s["kind"] == k)) for k, _ in COMPOSITION] == COMPOSITION
    got, attempt, dropped = assign(pool, slots, pm, SEED)
    for s in slots:
        b = got[s["slot"]]
        rows = [REG[r] for r in s["rows"]]
        s["base"] = {"run_id": b["run_id"], "condition": b["condition"], "probe_id": b["probe_id"],
                     "words": b["words"],
                     "exact_hit_rows": [r["id"] for r in REGISTRY if exact_hit(b["text"], r)],
                     "base_key_hits": {r["id"]: key_hits(b["text"], r) for r in REGISTRY if key_hits(b["text"], r)},
                     "penalty": penalty(b, rows, pm)}
    plan = {"seed": SEED, "attempt": attempt, "pool": len(pool),
            "dropped": [{"run_id": b["run_id"], "probe_id": b["probe_id"]} for b in dropped], "slots": slots}
    os.makedirs(os.path.dirname(PLAN), exist_ok=True)
    with open(PLAN, "w", encoding="utf-8") as f:
        json.dump(plan, f, indent=1, sort_keys=True)
        f.write("\n")
    print("wrote %s: %d slots, attempt %d, %d distinct probe_ids, dropped %d" % (
        PLAN, len(slots), attempt, len({s["base"]["probe_id"] for s in slots}), len(dropped)))


if __name__ == "__main__":
    main()
