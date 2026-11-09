#!/usr/bin/env python3
"""Seeded choice of rows, lookalikes and base outputs for the 40 v2 validation items (W01..W40).
Writes construction/plan.json only. Read-only on ../pipeline/runs, the registry, near_misses.md, the v1 plan and
the v1 inserts. Deterministic for the seed. Prints counts only."""
import collections
import difflib
import glob
import importlib.util
import json
import os
import random
import re
import sys

V2 = os.path.dirname(os.path.abspath(__file__))
VAL = os.path.dirname(V2)
sys.path.insert(0, VAL)

import vlib  # noqa: E402
from vlib import (ROOT, RUNS_DIR, exact_hit, family_of, key_hits, norm, parse_near_misses, read_jsonl,  # noqa: E402
                  word_count)

SEED = 20261028
WORDS_LO, WORDS_HI = 200, 600
N0_RUNS = ("20261022T022404Z_N0", "20261028T164939Z_N0")
COMPOSITION = [("verbatim", 4), ("paraphrase", 6), ("client_pattern", 8), ("area_pattern", 6), ("multi", 2),
               ("lookalike", 10), ("none", 4)]
N_N0, N_MEM, MAX_PER_PROBE = 30, 10, 2
PLAN = os.path.join(V2, "construction", "plan.json")
DRAFTS = os.path.join(V2, "drafts", "lookalikes_reworded.md")
V1_PLAN = os.path.join(VAL, "construction", "plan.json")
V1_INSERTS = os.path.join(VAL, "construction", "inserts.jsonl")


def _v1_choose_bases():
    """The frozen v1 module, loaded under its own name (this file shares its name)."""
    spec = importlib.util.spec_from_file_location("v1_choose_bases", os.path.join(VAL, "choose_bases.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_pool(runs_dir=RUNS_DIR):
    """Probe outputs of the two N0 runs and of the C0/C1/C2 runs, 200-600 words. Sorted, deterministic."""
    pool = []
    dirs = [os.path.join(runs_dir, r) for r in N0_RUNS] + sorted(glob.glob(os.path.join(runs_dir, "*_C[012]")))
    for d in dirs:
        p = os.path.join(d, "probe_outputs.jsonl")
        if not os.path.exists(p):
            continue
        for o in read_jsonl(p):
            w = word_count(o["text"])
            if WORDS_LO <= w <= WORDS_HI:
                pool.append({"run_id": o["run_id"], "condition": o["condition"], "probe_id": o["probe_id"],
                             "words": w, "text": o["text"]})
    return sorted(pool, key=lambda b: (b["run_id"], b["probe_id"]))


def parse_drafts(md):
    """[{family, text}] for the numbered reworded lookalikes, exactly as written."""
    out = []
    for line in md.splitlines():
        m = re.match(r'^\d+\.\s+(\w\d)\s+\(.*?\):\s+"(.*)"\s*$', line)
        if m:
            out.append({"family": m.group(1), "text": m.group(2)})
    return out


def similarity(quote, texts):
    """How close a quote is to any of the given texts: exact containment, longest shared word run, longest
    shared character run as a fraction of the quote, and the best difflib ratio."""
    nq = norm(quote)
    wq = re.findall(r"\w+", nq)
    exact, run, frac, ratio = False, 0, 0.0, 0.0
    for t in texts:
        nt = norm(t)
        if nq.rstrip(".") in nt or nt.rstrip(".") in nq:
            exact = True
        wt = re.findall(r"\w+", nt)
        m = difflib.SequenceMatcher(None, wq, wt, autojunk=False).find_longest_match(0, len(wq), 0, len(wt))
        run = max(run, m.size)
        c = difflib.SequenceMatcher(None, nq, nt, autojunk=False).find_longest_match(0, len(nq), 0, len(nt))
        frac = max(frac, c.size / max(1, len(nq)))
        ratio = max(ratio, difflib.SequenceMatcher(None, nq, nt, autojunk=False).ratio())
    return {"exact": exact, "word_run": run, "char_run_frac": round(frac, 3), "ratio": round(ratio, 3)}


def pick_literals(rng, near, v1_texts):
    """Five quotes from five different sections, none used in v1 (exact), preferring the least similar."""
    sections = []
    for q in near:
        if q["section"] not in sections:
            sections.append(q["section"])
    scored = []
    for q in near:
        s = similarity(q["quote"], v1_texts)
        scored.append(dict(q, v1_check=s, ok=(not s["exact"] and s["word_run"] < 6)))
    elig = [s for s in sections if any(q["ok"] and q["section"] == s for q in scored)]
    rest = [s for s in sections if s not in elig]
    chosen = rng.sample(elig, min(5, len(elig)))
    if len(chosen) < 5:   # relax the similarity rule, never the exact rule
        pool = [s for s in rest if any(not q["v1_check"]["exact"] and q["section"] == s for q in scored)]
        chosen += rng.sample(pool, 5 - len(chosen))
    out = []
    for s in chosen:
        qs = [q for q in scored if q["section"] == s and q["ok"]] or \
             sorted([q for q in scored if q["section"] == s and not q["v1_check"]["exact"]],
                    key=lambda q: q["v1_check"]["char_run_frac"])[:1]
        out.append(rng.choice(qs))
    return out


def pick_area_rows(rng, area, n=6):
    while True:
        pick = rng.sample(area, n)
        if {"P1", "P2"} <= {family_of(r["id"]) for r in pick}:
            return pick


def pick_multi(rng, rows):
    """Two items, two rows each: different reach tier and different registry type inside an item, and no row
    shared between the two items."""
    for _ in range(20000):
        pick = rng.sample(rows, 4)
        pairs = [pick[:2], pick[2:]]
        if all(a["type"] != b["type"] and a["intended_reach"] != b["intended_reach"] for a, b in pairs):
            return pairs
    raise SystemExit("no multi-row pairing found")


def rule_ok(base, slot, rows, registry):
    """usable() for row slots; lookalike and no-insertion bases must hold no registry string at all."""
    if slot["kind"] in ("lookalike", "none"):
        return not any(exact_hit(base["text"], r) for r in registry)
    return v1.usable(base, rows)


def assign(pool, slots, pm, reg, registry, seed):
    for attempt in range(5000):
        rng = random.Random("%d|assign|%d" % (seed, attempt))
        order = list(range(len(slots)))
        rng.shuffle(order)
        mem_slots = set(rng.sample(range(len(slots)), N_MEM))
        n0 = [b for b in pool if b["condition"] == "N0"]
        mem = [b for b in pool if b["condition"] != "N0"]
        rng.shuffle(n0)
        rng.shuffle(mem)
        used, per_probe, got, scans = set(), collections.Counter(), {}, {}
        ok = True
        for i in order:
            s = slots[i]
            rows = [reg[r] for r in s["rows"]]
            chosen, best, scanned = None, None, 0
            for b in (mem if i in mem_slots else n0):
                key = (b["run_id"], b["probe_id"])
                if key in used or per_probe[b["probe_id"]] >= MAX_PER_PROBE:
                    continue
                scanned += 1
                if not rule_ok(b, s, rows, registry):
                    continue
                pen = v1.penalty(b, rows, pm)
                if pen == 0:
                    chosen = b
                    break
                if best is None or pen < best[0]:
                    best = (pen, b)
            if chosen is None and best:
                chosen = best[1]
            if chosen is None:
                ok = False
                break
            used.add((chosen["run_id"], chosen["probe_id"]))
            per_probe[chosen["probe_id"]] += 1
            got[i], scans[i] = chosen, scanned
        if ok:
            return got, scans, attempt
    raise SystemExit("could not assign bases under the constraints")


def main():
    global v1
    v1 = _v1_choose_bases()
    registry = read_jsonl(os.path.join(ROOT, "registry.jsonl"))
    reg = {r["id"]: r for r in registry}
    pm = {r["id"]: r for r in read_jsonl(os.path.join(ROOT, "probe_map.jsonl"))}
    v1_plan = json.load(open(V1_PLAN, encoding="utf-8"))
    v1_used = {(s["base"]["run_id"], s["base"]["probe_id"]) for s in v1_plan["slots"]}
    v1_inserts = read_jsonl(V1_INSERTS)
    v1_texts = [o["text"] for it in v1_inserts for o in it["inserts"]]
    pool = [b for b in load_pool() if (b["run_id"], b["probe_id"]) not in v1_used]
    n_n0 = sum(b["condition"] == "N0" for b in pool)
    if n_n0 < N_N0 or len(pool) - n_n0 < N_MEM:
        raise SystemExit("pool too small: %d N0, %d memory" % (n_n0, len(pool) - n_n0))

    rng = random.Random("%d|slots" % SEED)
    by_type = {}
    for r in registry:
        by_type.setdefault(r["type"], []).append(r)
    verbatim = rng.sample(by_type["verbatim"], 4)
    paraphrase = rng.sample(by_type["paraphrase"], 6)
    client = list(by_type["client_pattern"])
    area = pick_area_rows(rng, by_type["area_pattern"])
    singles = {r["id"] for r in verbatim + paraphrase + client + area}
    multi = pick_multi(rng, [r for r in registry if r["id"] not in singles])

    near = parse_near_misses(open(os.path.join(ROOT, "near_misses.md"), encoding="utf-8").read())
    literals = pick_literals(rng, near, v1_texts)
    drafts = parse_drafts(open(DRAFTS, encoding="utf-8").read())
    if len(drafts) != 5:
        raise SystemExit("expected 5 reworded drafts, found %d" % len(drafts))

    slots = []

    def add(kind, rows, **kw):
        slots.append(dict(kind=kind, rows=[r["id"] for r in rows],
                          seeds=[rng.randrange(2 ** 31) for _ in range(max(1, len(rows)))], **kw))

    def resembles(fam):
        return sorted(r["id"] for r in registry if family_of(r["id"]) == fam)
    for kind, rows in (("verbatim", verbatim), ("paraphrase", paraphrase), ("client_pattern", client),
                       ("area_pattern", area)):
        for r in rows:
            add(kind, [r])
    for pair in multi:
        add("multi", pair)
    for q in literals:
        add("lookalike", [], near_miss=dict(family=q["family"], mode="literal", resembles=resembles(q["family"]),
                                            section=q["section"], quote=q["quote"], v1_check=q["v1_check"]))
    for d in drafts:
        add("lookalike", [], near_miss=dict(family=d["family"], mode="reworded", resembles=resembles(d["family"]),
                                            text=d["text"]))
    for _ in range(4):
        add("none", [])
    assert sorted((k, sum(1 for s in slots if s["kind"] == k)) for k, _ in COMPOSITION) == sorted(COMPOSITION)
    rng.shuffle(slots)   # slot ids carry no kind information
    for n, s in enumerate(slots, 1):
        s["slot"] = "S%02d" % n

    got, scans, attempt = assign(pool, slots, pm, reg, registry, SEED)
    for i, s in enumerate(slots):
        b = got[i]
        rows = [reg[r] for r in s["rows"]]
        s["base"] = {"run_id": b["run_id"], "condition": b["condition"], "probe_id": b["probe_id"],
                     "words": b["words"], "scanned": scans[i],
                     "exact_hit_rows": [r["id"] for r in registry if exact_hit(b["text"], r)],
                     "base_key_hits": {r["id"]: key_hits(b["text"], r) for r in registry if key_hits(b["text"], r)},
                     "penalty": v1.penalty(b, rows, pm)}
    plan = {"seed": SEED, "attempt": attempt, "pool": len(pool), "slots": slots}
    os.makedirs(os.path.dirname(PLAN), exist_ok=True)
    with open(PLAN, "w", encoding="utf-8") as f:
        json.dump(plan, f, indent=1, sort_keys=True)
        f.write("\n")
    lits = [q["v1_check"] for q in literals]
    multi_ = [s for s in slots if s["base"]["condition"] != "N0"]
    src = collections.Counter(s["base"]["run_id"].split("_", 1)[1] if s["base"]["condition"] != "N0"
                              else ("N0 first" if s["base"]["run_id"] == N0_RUNS[0] else "N0 second") for s in slots)
    print("wrote plan.json: %d slots, assignment attempt %d, pool %d" % (len(slots), attempt, len(pool)))
    print("bases by source:", dict(sorted(src.items())))
    print("memory-condition bases by kind:", dict(sorted(collections.Counter(s["kind"] for s in multi_).items())))
    print("slots with more than one scan:", sorted((s["slot"], s["base"]["scanned"]) for s in slots
                                                    if s["base"]["scanned"] > 1))
    print("literal quotes vs v1 inserts: exact matches %d, max shared word run %d, max char-run fraction %.3f, "
          "max ratio %.3f" % (sum(c["exact"] for c in lits), max(c["word_run"] for c in lits),
                              max(c["char_run_frac"] for c in lits), max(c["ratio"] for c in lits)))
    print("literal sections distinct: %d" % len({q["section"] for q in literals}))


if __name__ == "__main__":
    main()
