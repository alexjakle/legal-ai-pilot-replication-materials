#!/usr/bin/env python3
"""Assemble the 40 validation items from construction/plan.json (seeded bases) and
construction/inserts.jsonl (hand-written sentences). Checks every rule, then writes

  items.jsonl                  opaque id + text only
  for_labelling.md             registry rows once, then the items
  labels_template.csv          blank sheet for Alex
  construction/labels.jsonl    expected rows, bases, placements (never copied into the three files above)

Deterministic for the seed. Read-only on ../pipeline/runs, the registry and near_misses.md."""
import argparse
import csv
import io
import json
import os
import random
import re

import vlib
from vlib import (COMPOSITION, HERE, ROOT, SEED, STRENGTH, exact_hit, family_of, insert_sentences, key_hits, load_pool,
                  norm, parse_near_misses, read_jsonl)

CONSTRUCTION = os.path.join(HERE, "construction")
NGRAM = 5


class BuildError(Exception):
    pass


def ngrams(s, n=NGRAM):
    w = re.findall(r"\w+", norm(s))
    return {tuple(w[i:i + n]) for i in range(len(w) - n + 1)}


def check_inserts(plan, inserts, registry, near_misses):
    """Return a list of problems (empty when every rule holds) and per-item extra key hits (information)."""
    reg = {r["id"]: r for r in registry}
    problems, extra = [], {}
    by_item = {i["item"]: i for i in inserts}
    kinds = {}
    for s in plan["slots"]:
        kinds[s["kind"]] = kinds.get(s["kind"], 0) + 1
        ins = by_item.get(s["slot"])
        if ins is None:
            problems.append("%s: no entry in inserts.jsonl" % s["slot"])
            continue
        b = s["base"]
        if (ins["base_run"], ins["base_probe"]) != (b["run_id"], b["probe_id"]):
            problems.append("%s: base differs from plan" % s["slot"])
        if ins["kind"] != s["kind"]:
            problems.append("%s: kind differs from plan" % s["slot"])
        n = len(ins["inserts"])
        if s["kind"] == "none":
            if n:
                problems.append("%s: a no-insertion item has inserts" % s["slot"])
            continue
        want = len(s["rows"]) if s["rows"] else 1
        if n != want:
            problems.append("%s: %d inserts, plan wants %d" % (s["slot"], n, want))
            continue
        total_sent = 0
        for k, one in enumerate(ins["inserts"]):
            if one["position_seed"] != s["seeds"][k]:
                problems.append("%s: position seed differs from plan" % s["slot"])
            text = one["text"]
            total_sent += len(vlib._boundaries(text))
            got = [r["id"] for r in one["rows"]]
            exp = [s["rows"][k]] if s["rows"] else []
            if got != exp:
                problems.append("%s: insert %d rows %s != plan %s" % (s["slot"], k, got, exp))
            for r in one["rows"]:
                row = reg[r["id"]]
                if r["strength"] != STRENGTH[row["type"]]:
                    problems.append("%s: strength %s for %s" % (s["slot"], r["strength"], row["type"]))
                if row["type"] == "verbatim":
                    if not exact_hit(text, row):
                        problems.append("%s: verbatim insert lacks the exact string %r" % (s["slot"], row["text"]))
                else:
                    hits = key_hits(text, row)
                    if hits:
                        problems.append("%s: %s insert contains detection keys %s" % (s["slot"], r["id"], hits))
            for row in registry:
                if row["type"] == "verbatim" and exact_hit(text, row) and row["id"] not in [r["id"] for r in one["rows"]]:
                    problems.append("%s: insert contains the exact string of %s" % (s["slot"], row["id"]))
            others = sorted(r["id"] for r in registry if r["id"] not in [x["id"] for x in one["rows"]]
                            and key_hits(text, r))
            if others:
                extra.setdefault(s["slot"], {})[str(k)] = others
        if total_sent > 2:
            problems.append("%s: %d inserted sentences (max 2)" % (s["slot"], total_sent))
        if s["kind"] == "near_miss":
            nm = s["near_miss"]
            meta = ins.get("near_miss", {})
            if meta.get("family") != nm["family"] or meta.get("mode") != nm["mode"]:
                problems.append("%s: near_miss metadata differs from plan" % s["slot"])
            text = ins["inserts"][0]["text"]
            if nm["mode"] == "literal" and norm(nm["quote"]).rstrip(".") not in norm(text):
                problems.append("%s: literal near-miss must contain the quote as written" % s["slot"])
            if nm["mode"] == "reworded" and ngrams(nm["quote"]) & ngrams(text):
                problems.append("%s: reworded near-miss shares a %d-word run with the quote" % (s["slot"], NGRAM))
    if sorted(kinds.items(), key=lambda x: x[0]) != sorted(COMPOSITION, key=lambda x: x[0]):
        problems.append("composition %s != %s" % (kinds, dict(COMPOSITION)))
    return problems, extra


def order_slots(slots, seed=SEED):
    """Seeded shuffle; no two neighbours share a base (run, probe) or a probe_id."""
    rng = random.Random("%d|order" % seed)
    for _ in range(100000):
        cand = slots[:]
        rng.shuffle(cand)
        if all(a["base"]["probe_id"] != b["base"]["probe_id"] for a, b in zip(cand, cand[1:])):
            return cand
    raise BuildError("no ordering without adjacent shared probe_ids")


def assemble(plan, inserts, bases):
    by_item = {i["item"]: i for i in inserts}
    out = {}
    for s in plan["slots"]:
        b = bases[(s["base"]["run_id"], s["base"]["probe_id"])]
        ins = by_item[s["slot"]]
        pairs = [(o["text"], o["position_seed"]) for o in ins["inserts"]]
        text, places = (b["text"], []) if not pairs else insert_sentences(b["text"], pairs)
        out[s["slot"]] = (text, places)
    return out


def labelling_md(registry, items):
    lines = ["# Labelling sheet", "",
             "For each item below, list every registry row below that the text contains, whatever the strength:",
             "verbatim (the exact string appears), paraphrase (the same specific fact is restated) or pattern",
             "(the practice or instruction is stated in general terms). Fill in `labels_template.csv`:",
             "`rows_present` holds registry ids separated by semicolons, or `none`; `strength` holds",
             "`ID=strength` pairs separated by semicolons (e.g. `F01=verbatim;A1-A-1=pattern`); `notes` is free text.",
             "", "## Registry rows", ""]
    for r in registry:
        lines.append("- **%s**: %s" % (r["id"], r["text"]))
    lines += ["", "## Items", ""]
    for it in items:
        lines += ["---", "", "### %s" % it["id"], ""]
        lines += [("> " + ln) if ln.strip() else ">" for ln in it["text"].split("\n")]
        lines.append("")
    return "\n".join(lines)


def template_csv(items):
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["item_id", "rows_present", "strength", "notes"])
    for it in items:
        w.writerow([it["id"], "", "", ""])
    return buf.getvalue()


def build(plan, inserts, registry, bases, near_md, outdir):
    problems, extra = check_inserts(plan, inserts, registry, parse_near_misses(near_md))
    if problems:
        raise BuildError("\n".join(problems))
    texts = assemble(plan, inserts, bases)
    slots = order_slots(plan["slots"])
    by_item = {i["item"]: i for i in inserts}
    reg = {r["id"]: r for r in registry}
    items, labels = [], []
    for n, s in enumerate(slots, 1):
        vid = "V%02d" % n
        text, places = texts[s["slot"]]
        ins = by_item[s["slot"]]
        expected = [dict(row=r["id"], strength=r["strength"]) for o in ins["inserts"] for r in o["rows"]]
        fam = {e["row"]: sorted(r["id"] for r in registry if family_of(r["id"]) and
                                family_of(r["id"]) == family_of(e["row"]) and r["id"] != e["row"])
               for e in expected if reg[e["row"]]["type"] in ("client_pattern", "area_pattern")}
        items.append({"id": vid, "text": text})
        labels.append({"id": vid, "slot": s["slot"], "kind": s["kind"], "expected": expected,
                       "inserted_text": [o["text"] for o in ins["inserts"]], "places": places,
                       "family_siblings": fam, "near_miss": ins.get("near_miss"),
                       "base": s["base"], "insert_extra_key_hits": extra.get(s["slot"], {})})
    os.makedirs(os.path.join(outdir, "construction"), exist_ok=True)
    vlib_write(os.path.join(outdir, "items.jsonl"), items)
    vlib_write(os.path.join(outdir, "construction", "labels.jsonl"), labels)
    with open(os.path.join(outdir, "for_labelling.md"), "w", encoding="utf-8") as f:
        f.write(labelling_md(registry, items))
    with open(os.path.join(outdir, "labels_template.csv"), "w", encoding="utf-8") as f:
        f.write(template_csv(items))
    return items, labels


def vlib_write(path, rows):
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=HERE)
    a = ap.parse_args(argv)
    plan = json.load(open(os.path.join(CONSTRUCTION, "plan.json"), encoding="utf-8"))
    inserts = read_jsonl(os.path.join(CONSTRUCTION, "inserts.jsonl"))
    registry = read_jsonl(os.path.join(ROOT, "registry.jsonl"))
    near_md = open(os.path.join(ROOT, "near_misses.md"), encoding="utf-8").read()
    bases = {(b["run_id"], b["probe_id"]): b for b in load_pool()}
    try:
        items, labels = build(plan, inserts, registry, bases, near_md, a.out)
    except BuildError as e:
        raise SystemExit("build failed:\n%s" % e)
    print("wrote %d items to %s" % (len(items), a.out))


if __name__ == "__main__":
    main()
