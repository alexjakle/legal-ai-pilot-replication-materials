#!/usr/bin/env python3
"""Assemble the 40 v2 validation items (W01..W40) from construction/plan.json (seeded rows, lookalikes and bases),
construction/row_bank.jsonl (one fresh sentence per registry row) and drafts/lookalikes_reworded.md. Checks every
rule, then writes

  items.jsonl                  opaque id + text only
  construction/inserts.jsonl   the inserted sentences per slot
  construction/labels.jsonl    the answer key (never copied into items.jsonl)

Deterministic for the seed. Read-only on ../pipeline/runs, the registry and near_misses.md. Prints counts only."""
import argparse
import collections
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
from vlib import ROOT, STRENGTH, exact_hit, family_of, insert_sentences, key_hits, norm, parse_near_misses, read_jsonl  # noqa: E402


def _sibling(name):
    mod = sys.modules.get("v2_" + name)
    if mod is None:
        spec = importlib.util.spec_from_file_location("v2_" + name, os.path.join(V2, name + ".py"))
        mod = importlib.util.module_from_spec(spec)
        sys.modules["v2_" + name] = mod
        spec.loader.exec_module(mod)
    return mod


cb = _sibling("choose_bases")
SEED = cb.SEED
CONSTRUCTION = os.path.join(V2, "construction")
NGRAM = 5
NGRAM_REWORDED_FAIL = 6    # a reworded lookalike may not share a run this long with a near-miss quote or a v1 insert
LEAD_INS = ('Another file has this sentence: "%s"', 'The wording elsewhere in the file reads: "%s"',
            'A related document says: "%s"')


class BuildError(Exception):
    pass


def ngrams(s, n=NGRAM):
    w = re.findall(r"\w+", norm(s))
    return {tuple(w[i:i + n]) for i in range(len(w) - n + 1)}


def literal_sentence(quote, seed):
    q = quote if quote.rstrip()[-1] in ".!?" else quote + "."
    return random.Random(seed).choice(LEAD_INS) % q if q.endswith(".") else None


def make_inserts(plan, bank, lookalike_text):
    """The insert entries (same shape as v1) for every slot."""
    out = []
    for s in plan["slots"]:
        ins = []
        if s["kind"] in ("verbatim", "paraphrase", "client_pattern", "area_pattern", "multi"):
            for k, rid in enumerate(s["rows"]):
                ins.append({"position_seed": s["seeds"][k], "text": bank[rid], "rows": [{"id": rid, "strength": None}]})
        entry = {"item": s["slot"], "kind": s["kind"], "base_run": s["base"]["run_id"], "base_probe": s["base"]["probe_id"]}
        if s["kind"] == "lookalike":
            nm = s["near_miss"]
            entry["near_miss"] = {k: nm[k] for k in ("family", "mode", "resembles")}
            ins.append({"position_seed": s["seeds"][0], "text": lookalike_text(s), "rows": []})
        entry["inserts"] = ins
        out.append(entry)
    return out


def check(plan, inserts, registry, near_md, v1_texts):
    """Problems (empty when every rule holds) and per-slot extra key hits (information)."""
    reg = {r["id"]: r for r in registry}
    by_item = {i["item"]: i for i in inserts}
    quotes = [q["quote"] for q in parse_near_misses(near_md)]
    own = " ".join(r["text"].lower() for r in registry) + near_md.lower()
    unique = [k for r in registry for k in r["detection_keys"] if k.lower() not in own]
    problems, extra, kinds = [], {}, collections.Counter()
    seen_pairs, per_probe, rows_by_single = set(), collections.Counter(), collections.Counter()
    for s in plan["slots"]:
        kinds[s["kind"]] += 1
        b = s["base"]
        if (b["run_id"], b["probe_id"]) in seen_pairs:
            problems.append("%s: base used twice" % s["slot"])
        seen_pairs.add((b["run_id"], b["probe_id"]))
        per_probe[b["probe_id"]] += 1
        if not cb.WORDS_LO <= b["words"] <= cb.WORDS_HI:
            problems.append("%s: base words %d outside %d-%d" % (s["slot"], b["words"], cb.WORDS_LO, cb.WORDS_HI))
        ins = by_item[s["slot"]]
        if s["kind"] == "none":
            if ins["inserts"]:
                problems.append("%s: a no-insertion item has inserts" % s["slot"])
            continue
        want = len(s["rows"]) if s["rows"] else 1
        if len(ins["inserts"]) != want:
            problems.append("%s: %d inserts, plan wants %d" % (s["slot"], len(ins["inserts"]), want))
            continue
        total_sent = 0
        for k, one in enumerate(ins["inserts"]):
            text = one["text"]
            total_sent += len(vlib._boundaries(text))
            if one["position_seed"] != s["seeds"][k]:
                problems.append("%s: position seed differs from plan" % s["slot"])
            for r in one["rows"]:
                row = reg[r["id"]]
                if r["strength"] != STRENGTH[row["type"]]:
                    problems.append("%s: strength %s for %s" % (s["slot"], r["strength"], row["type"]))
                if row["type"] == "verbatim":
                    if not exact_hit(text, row):
                        problems.append("%s: verbatim insert lacks the exact string of %s" % (s["slot"], row["id"]))
                elif key_hits(text, row):
                    problems.append("%s: %s insert contains detection keys %s" % (s["slot"], row["id"], key_hits(text, row)))
                if ngrams(text) & set().union(*[ngrams(t) for t in v1_texts]):
                    problems.append("%s: insert shares a %d-word run with a v1 insert" % (s["slot"], NGRAM))
            ids = [r["id"] for r in one["rows"]]
            for row in registry:
                if row["type"] == "verbatim" and exact_hit(text, row) and row["id"] not in ids:
                    problems.append("%s: insert contains the exact string of %s" % (s["slot"], row["id"]))
            others = sorted(r["id"] for r in registry if r["id"] not in ids and key_hits(text, r))
            if others:
                extra.setdefault(s["slot"], {})[str(k)] = others
        if total_sent > 2:
            problems.append("%s: %d inserted sentences (max 2)" % (s["slot"], total_sent))
        if s["kind"] == "lookalike":
            nm, text = s["near_miss"], ins["inserts"][0]["text"]
            if [k for k in unique if k.lower() in text.lower()]:
                problems.append("%s: lookalike contains a unique detection key" % s["slot"])
            if nm["mode"] == "literal" and norm(nm["quote"]).rstrip(".") not in norm(text):
                problems.append("%s: literal lookalike lacks the quote as written" % s["slot"])
            if nm["mode"] == "reworded":
                if norm(text) != norm(nm["text"]):
                    problems.append("%s: reworded lookalike differs from the approved draft" % s["slot"])
                if any(key_hits(text, r) for r in registry):
                    problems.append("%s: reworded lookalike contains a detection key" % s["slot"])
                if ngrams(text, NGRAM_REWORDED_FAIL) & set().union(*[ngrams(t, NGRAM_REWORDED_FAIL) for t in quotes + v1_texts]):
                    problems.append("%s: reworded lookalike shares a %d-word run with a quote or v1 insert"
                                    % (s["slot"], NGRAM_REWORDED_FAIL))
        for rid in s["rows"]:
            if s["kind"] != "multi":
                rows_by_single[rid] += 1
    if any(n > MAX for n in per_probe.values()):
        problems.append("a probe_id is used by more than %d bases" % MAX)
    if sorted(kinds.items()) != sorted(cb.COMPOSITION):
        problems.append("composition %s != %s" % (dict(kinds), dict(cb.COMPOSITION)))
    modes = collections.Counter(s["near_miss"]["mode"] for s in plan["slots"] if s["kind"] == "lookalike")
    if modes != {"literal": 5, "reworded": 5}:
        problems.append("lookalike modes %s" % dict(modes))
    if collections.Counter(s["base"]["condition"] == "N0" for s in plan["slots"]) != {True: cb.N_N0, False: cb.N_MEM}:
        problems.append("base sources are not %d N0 and %d memory-condition" % (cb.N_N0, cb.N_MEM))
    return problems, extra


MAX = cb.MAX_PER_PROBE


def order_slots(slots, seed=SEED):
    """Seeded shuffle; no two neighbours share a probe_id."""
    rng = random.Random("%d|order" % seed)
    for _ in range(100000):
        cand = slots[:]
        rng.shuffle(cand)
        if all(a["base"]["probe_id"] != b["base"]["probe_id"] for a, b in zip(cand, cand[1:])):
            return cand
    raise BuildError("no ordering without adjacent shared probe_ids")


def vwrite(path, rows):
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")


def build(plan, bank, registry, bases, near_md, v1_texts, outdir):
    reg = {r["id"]: r for r in registry}
    lit_seed = {s["slot"]: s["seeds"][0] for s in plan["slots"]}

    def lookalike_text(s):
        nm = s["near_miss"]
        return nm["text"] if nm["mode"] == "reworded" else literal_sentence(nm["quote"], lit_seed[s["slot"]])
    inserts = make_inserts(plan, bank, lookalike_text)
    for e in inserts:
        for o in e["inserts"]:
            for r in o["rows"]:
                r["strength"] = STRENGTH[reg[r["id"]]["type"]]
    problems, extra = check(plan, inserts, registry, near_md, v1_texts)
    if problems:
        raise BuildError("\n".join(problems))
    by_item = {i["item"]: i for i in inserts}
    slots = order_slots(plan["slots"])
    items, labels = [], []
    for n, s in enumerate(slots, 1):
        wid = "W%02d" % n
        b = bases[(s["base"]["run_id"], s["base"]["probe_id"])]
        ins = by_item[s["slot"]]
        pairs = [(o["text"], o["position_seed"]) for o in ins["inserts"]]
        text, places = (b["text"], []) if not pairs else insert_sentences(b["text"], pairs)
        for o in ins["inserts"]:
            if o["text"].strip() not in text:
                raise BuildError("%s: inserted sentence missing from the assembled text" % s["slot"])
        expected = [dict(row=r["id"], strength=r["strength"]) for o in ins["inserts"] for r in o["rows"]]
        fam = {e["row"]: sorted(r["id"] for r in registry if family_of(r["id"]) and
                                family_of(r["id"]) == family_of(e["row"]) and r["id"] != e["row"])
               for e in expected if reg[e["row"]]["type"] in ("client_pattern", "area_pattern")}
        items.append({"id": wid, "text": text})
        labels.append({"id": wid, "slot": s["slot"], "kind": s["kind"], "expected": expected,
                       "inserted_text": [o["text"] for o in ins["inserts"]], "places": places,
                       "family_siblings": fam, "near_miss": ins.get("near_miss"), "base": s["base"],
                       "insert_extra_key_hits": extra.get(s["slot"], {})})
    os.makedirs(os.path.join(outdir, "construction"), exist_ok=True)
    vwrite(os.path.join(outdir, "items.jsonl"), items)
    vwrite(os.path.join(outdir, "construction", "inserts.jsonl"), inserts)
    vwrite(os.path.join(outdir, "construction", "labels.jsonl"), labels)
    return items, labels, extra


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=V2)
    a = ap.parse_args(argv)
    plan = json.load(open(os.path.join(CONSTRUCTION, "plan.json"), encoding="utf-8"))
    bank = {r["id"]: r["text"] for r in read_jsonl(os.path.join(CONSTRUCTION, "row_bank.jsonl"))}
    registry = read_jsonl(os.path.join(ROOT, "registry.jsonl"))
    if sorted(bank) != sorted(r["id"] for r in registry):
        raise SystemExit("row_bank.jsonl does not cover the registry exactly")
    near_md = open(os.path.join(ROOT, "near_misses.md"), encoding="utf-8").read()
    v1_texts = [o["text"] for it in read_jsonl(cb.V1_INSERTS) for o in it["inserts"]]
    bases = {(b["run_id"], b["probe_id"]): b for b in cb.load_pool()}
    try:
        items, labels, extra = build(plan, bank, registry, bases, near_md, v1_texts, a.out)
    except BuildError as e:
        with open(os.path.join(CONSTRUCTION, "build_errors.txt"), "w", encoding="utf-8") as f:
            f.write(str(e) + "\n")
        raise SystemExit("build failed: %d problems, see construction/build_errors.txt" % len(str(e).splitlines()))
    words = [len(i["text"].split()) for i in items]
    print("wrote %d items to %s" % (len(items), a.out))
    print("kinds:", dict(sorted(collections.Counter(l["kind"] for l in labels).items())))
    print("item words: min %d, max %d" % (min(words), max(words)))
    print("slots whose insert hits other rows' detection keys: %d" % len(extra))


if __name__ == "__main__":
    main()
