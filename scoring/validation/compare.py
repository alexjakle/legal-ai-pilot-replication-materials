#!/usr/bin/env python3
"""Compare the judge's run on the validation items with Alex's labels (the truth) and the construction labels.

  compare.py --labels LABELS.csv [--judge ../scores/validation_20261019] [--out report.md]
             [--families families.json] [--adjudication FILE.md ...] [--pre-rejudge]

Order of work, so nothing about construction is read before the labels are in:
  1. the filled-in labels must cover all items (a blank rows_present cell means not labelled; write `none` for no rows);
  2. the judge run must be complete, not a stub, judged exactly these items, and its prompt_hash must equal the
     hash in the committed live runs under scores/ (otherwise the report is refused, unless --pre-rejudge, which
     reports with a notice that the live runs have not been judged under this prompt);
  3. only then are the construction labels read.
Family mode (v2): compare.py --set v2 --family-labels labels_v2.csv [--pre-rejudge] [--out report.md]. Alex labels
24 units (the four families collapsed through families.json, every other row its own unit); the judge's row
detections are mapped to units; item agreement = equal unit sets, bar 90%, strength secondary. The same order of
work applies, and the construction labels are read last. No post-hoc corrections in v2.

Alex's labels cover the whole text and are the truth. The construction labels list inserted rows only, so any other
row Alex labels is reported as base content, not as an Alex error."""
import argparse
import csv
import os
import re
import sys

import vlib
from vlib import HERE, ROOT, STRENGTHS, read_json, read_jsonl
from judge.util import sha256_bytes

BAR = 0.90
TYPES = ("verbatim", "paraphrase", "client_pattern", "area_pattern")
TIERS = ("matter", "client", "firm")
DEFAULT_FAMILIES = os.path.join(HERE, "families.json")
DEFAULT_JUDGE = os.path.join(ROOT, "scores", "validation_%d" % vlib.SEED)


class Refuse(SystemExit):
    pass


# ---------------------------------------------------------------- inputs

def load_alex(path, item_ids, registry_ids):
    """{item: {"rows": set, "strength": {row: strength}, "notes": str}}; refuses on any unlabelled or malformed row."""
    with open(path, encoding="utf-8", newline="") as f:
        data = list(csv.DictReader(f))
    by = {r["item_id"].strip(): r for r in data if r.get("item_id")}
    missing = [i for i in item_ids if i not in by or not (by[i].get("rows_present") or "").strip()]
    if missing:
        raise Refuse("labels not complete: %d of %d items have no rows_present (write `none` for no rows); "
                     "first: %s" % (len(missing), len(item_ids), ", ".join(missing[:5])))
    extra = sorted(set(by) - set(item_ids))
    if extra:
        raise Refuse("labels name unknown items: %s" % ", ".join(extra[:5]))
    out, bad = {}, []
    for i in item_ids:
        r = by[i]
        raw = r["rows_present"].strip()
        rows = [] if raw.lower() == "none" else [t.strip() for t in raw.split(";") if t.strip()]
        unknown = [t for t in rows if t not in registry_ids]
        if unknown or len(set(rows)) != len(rows):
            bad.append("%s: %s" % (i, unknown or "duplicate rows"))
            continue
        strength, toks = {}, [t.strip() for t in (r.get("strength") or "").split(";") if t.strip()]
        if toks and all("=" in t for t in toks):
            for t in toks:
                k, v = [x.strip() for x in t.split("=", 1)]
                strength[k] = v
        elif toks and len(toks) == len(rows):
            strength = dict(zip(rows, toks))
        elif toks:
            bad.append("%s: strength cell is neither ID=strength pairs nor one value per row" % i)
            continue
        wrong = [v for k, v in strength.items() if v not in STRENGTHS or k not in rows]
        if wrong:
            bad.append("%s: bad strength entries %s" % (i, wrong))
            continue
        out[i] = {"rows": set(rows), "strength": strength, "notes": (r.get("notes") or "").strip()}
    if bad:
        raise Refuse("labels malformed:\n  " + "\n  ".join(bad))
    return out


def pre_rejudge_notice(m, scores_root):
    """Plain-words notice when the live runs carry a different prompt hash from the validation run, else None."""
    bad = sorted({x["prompt_hash"] for x in vlib.live_manifests(scores_root) if x["prompt_hash"] != m["prompt_hash"]})
    if not bad:
        return None
    return ("The live runs were judged under prompt hash %s, not under this prompt (%s). They have not been judged "
            "under this prompt, and this validation is not yet usable as a result for them." % (
                ", ".join(h[:12] for h in bad), m["prompt_hash"][:12]))


def check_judge_run(judge_dir, scores_root, items_path, item_ids, allow_stub=False, pre_rejudge=False):
    mpath = os.path.join(judge_dir, "manifest.json")
    if not os.path.exists(mpath):
        raise Refuse("no manifest.json in %s" % judge_dir)
    m = read_json(mpath)
    if m.get("kind") != "validation":
        raise Refuse("%s is not a validation run" % judge_dir)
    if m.get("status") != "complete":
        raise Refuse("judge run is %s; finish it first" % m.get("status"))
    if m.get("stub") and not allow_stub:
        raise Refuse("judge run is a stub run; refusing (use --allow-stub only in tests)")
    live = vlib.live_manifests(scores_root)
    if not live:
        raise Refuse("no committed live runs under %s to check the prompt hash against" % scores_root)
    hashes = {x["prompt_hash"] for x in live}
    if hashes != {m["prompt_hash"]} and not pre_rejudge:
        raise Refuse("prompt_hash %s differs from the live runs' %s; refusing to report" % (
            m["prompt_hash"][:12], ", ".join(sorted(h[:12] for h in hashes))))
    with open(items_path, "rb") as f:
        if sha256_bytes(f.read()) != m.get("items_hash"):
            raise Refuse("items.jsonl is not the file the judge run was made on")
    j = {x["item_id"]: x for x in read_jsonl(os.path.join(judge_dir, "judgments.jsonl"))}
    if sorted(j) != sorted(item_ids):
        raise Refuse("judge run does not cover exactly the items")
    return m, j


def judge_view(judgments):
    """{item: {row: {"verdict", "quote", "unverified"}}} for detected rows only."""
    out = {}
    for i, j in judgments.items():
        out[i] = {r["registry_id"]: {"verdict": r["verdict"], "quote": r.get("quote", ""),
                                     "unverified": r.get("quote_unverified", False)}
                  for r in j["rows"] if r["verdict"] != "absent"}
    return out


# ---------------------------------------------------------------- families and adjudication (post-hoc)

def load_families(path, registry_ids):
    """Returns row -> family. families.json maps row ids to a family id; unlisted rows are their own family."""
    try:
        raw = read_json(path)
    except (OSError, ValueError) as e:
        raise Refuse("cannot read families file %s: %s" % (path, e))
    if not isinstance(raw, dict) or not all(isinstance(k, str) and isinstance(v, str) and v for k, v in raw.items()):
        raise Refuse("families file %s must map row ids to family ids" % path)
    unknown = sorted(set(raw) - set(registry_ids))
    if unknown:
        raise Refuse("families file names unknown rows: %s" % ", ".join(unknown[:5]))
    return {r: raw.get(r, r) for r in registry_ids}


CASE_HEAD = re.compile(r"^## Case (\d+): (\S+?), (row|family) (\S+)(?:\s.*)?$")
RULING = re.compile(r"^Ruling:[ \t]*(.*?)[ \t]*$")


def parse_adjudication(paths, item_ids, row_to_family):
    """[(item, kind, target, yes)] with kind "row" or "family"; refuses on anything not exactly as specified."""
    fams = set(row_to_family.values())
    out, seen = [], {}
    for path in paths:
        try:
            with open(path, encoding="utf-8") as f:
                lines = f.read().split("\n")
        except OSError as e:
            raise Refuse("cannot read adjudication file %s: %s" % (path, e))
        cases, cur = [], None
        for ln in lines:
            if ln.startswith("## Case"):
                m = CASE_HEAD.match(ln)
                if not m:
                    raise Refuse("%s: malformed case header: %s" % (os.path.basename(path), ln.strip()))
                cur = {"n": m.group(1), "item": m.group(2), "kind": m.group(3), "target": m.group(4), "rulings": []}
                cases.append(cur)
            elif cur is not None and RULING.match(ln):
                cur["rulings"].append(RULING.match(ln).group(1))
        if not cases:
            raise Refuse("%s: no cases found" % os.path.basename(path))
        for c in cases:
            where = "%s case %s" % (os.path.basename(path), c["n"])
            if len(c["rulings"]) != 1:
                raise Refuse("%s: expected exactly one Ruling line, found %d" % (where, len(c["rulings"])))
            if c["rulings"][0] not in ("Yes", "No"):
                raise Refuse("%s: Ruling must be Yes or No, got %r" % (where, c["rulings"][0]))
            if c["item"] not in item_ids:
                raise Refuse("%s: unknown item %s" % (where, c["item"]))
            if c["kind"] == "row" and c["target"] not in row_to_family:
                raise Refuse("%s: unknown row %s" % (where, c["target"]))
            if c["kind"] == "family" and c["target"] not in fams:
                raise Refuse("%s: unknown family %s" % (where, c["target"]))
            key = (c["item"], c["kind"], c["target"])
            if key in seen:
                raise Refuse("%s: duplicate of %s" % (where, seen[key]))
            seen[key] = where
            out.append((c["item"], c["kind"], c["target"], c["rulings"][0] == "Yes"))
    return out


def family_sets(item_ids, rows_by_item, row_to_family):
    return {i: {row_to_family[r] for r in rows_by_item[i]} for i in item_ids}


def corrected_key(item_ids, alex_rows, rulings, row_to_family):
    """{item: set of families}: Alex's families with the rulings applied. Judge sets are not touched here."""
    key = family_sets(item_ids, alex_rows, row_to_family)
    for item, kind, target, yes in rulings:
        fam = row_to_family[target] if kind == "row" else target
        if yes:
            key[item].add(fam)
        elif kind == "family" or not any(row_to_family[r] == fam and r != target for r in alex_rows[item]):
            key[item].discard(fam)
    return key


def family_agreement(item_ids, judge_rows, alex_rows, row_to_family, rulings=None):
    """Items whose judge family set equals the key's family set (Alex's, or the corrected key when rulings given)."""
    key = (corrected_key(item_ids, alex_rows, rulings, row_to_family) if rulings is not None
           else family_sets(item_ids, alex_rows, row_to_family))
    jf = family_sets(item_ids, judge_rows, row_to_family)
    return [i for i in item_ids if jf[i] == key[i]]


# ---------------------------------------------------------------- analysis

def confusion(registry, item_ids, alex, judge, key):
    """{group: [TP, FP, FN, TN]} grouped by key(row)."""
    out = {}
    for r in registry:
        c = out.setdefault(key(r), [0, 0, 0, 0])
        for i in item_ids:
            a, j = r["id"] in alex[i]["rows"], r["id"] in judge[i]
            c[0 if a and j else 1 if j else 2 if a else 3] += 1
    return out


def analyze(registry, item_ids, alex, judge, construction, texts):
    reg = {r["id"]: r for r in registry}
    cons = {c["id"]: c for c in construction}
    res = {"n": len(item_ids)}
    res["matches"] = [i for i in item_ids if set(judge[i]) == alex[i]["rows"]]
    res["mismatch"] = [i for i in item_ids if i not in res["matches"]]
    res["by_tier"] = confusion(registry, item_ids, alex, judge, lambda r: r["intended_reach"])
    res["by_type"] = confusion(registry, item_ids, alex, judge, lambda r: r["type"])
    pairs = {t: [0, 0] for t in TYPES}
    mat, nostr = {}, 0
    for i in item_ids:
        for row in alex[i]["rows"] & set(judge[i]):
            a = alex[i]["strength"].get(row)
            if a is None:
                nostr += 1
                continue
            jv = judge[i][row]["verdict"]
            pairs[reg[row]["type"]][0] += 1
            pairs[reg[row]["type"]][1] += int(a == jv)
            mat[(a, jv)] = mat.get((a, jv), 0) + 1
    res["strength"] = {"pairs": pairs, "matrix": mat, "no_alex_strength": nostr}
    fp, fn = [], []
    for i in item_ids:
        for row in sorted(set(judge[i]) - alex[i]["rows"]):
            fp.append({"item": i, "row": row, "verdict": judge[i][row]["verdict"], "quote": judge[i][row]["quote"],
                       "unverified": judge[i][row]["unverified"]})
        # one inserted sentence per expected row, in the same order
        ins_text = dict(zip([e["row"] for e in cons[i]["expected"]], cons[i]["inserted_text"]))
        for row in sorted(alex[i]["rows"] - set(judge[i])):
            fn.append({"item": i, "row": row, "alex_strength": alex[i]["strength"].get(row),
                       "inserted": ins_text.get(row), "notes": alex[i]["notes"]})
    res["fp"], res["fn"] = fp, fn
    adj, base = [], []
    for i in item_ids:
        exp = {e["row"]: e["strength"] for e in cons[i]["expected"]}
        a = alex[i]
        for row in sorted(set(exp) - a["rows"]):
            adj.append({"item": i, "row": row, "what": "inserted row not labelled by Alex", "expected": exp[row],
                        "alex": None})
        for row in sorted(set(exp) & a["rows"]):
            s = a["strength"].get(row)
            if s is not None and s != exp[row]:
                adj.append({"item": i, "row": row, "what": "strength differs", "expected": exp[row], "alex": s})
        for row in sorted(a["rows"] - set(exp)):
            sib = [e for e, sibs in cons[i]["family_siblings"].items() if row in sibs]
            nm = cons[i]["near_miss"]
            base.append({"item": i, "row": row, "kind": cons[i]["kind"],
                         "family_sibling_of": sib[0] if sib else None,
                         "lookalike_row": bool(nm and row in nm.get("resembles", []))})
    res["adjudicate"], res["base_content"] = adj, base
    res["adjudicate_items"] = sorted({x["item"] for x in adj})
    near = []
    for i in item_ids:
        if cons[i]["kind"] != "near_miss":
            continue
        nm = cons[i]["near_miss"]
        res_rows = set(nm.get("resembles", []))
        near.append({"item": i, "family": nm["family"], "mode": nm["mode"], "resembles": sorted(res_rows),
                     "judge_hit_lookalike": sorted(res_rows & set(judge[i])),
                     "alex_hit_lookalike": sorted(res_rows & alex[i]["rows"]),
                     "match": set(judge[i]) == alex[i]["rows"],
                     "judge_rows": sorted(judge[i]), "alex_rows": sorted(alex[i]["rows"])})
    res["near"] = near
    res["unverified"] = sum(1 for i in item_ids for v in judge[i].values() if v["unverified"])
    return res


# ---------------------------------------------------------------- report

def pct(a, b):
    return "n/a" if not b else "%.0f%%" % (100.0 * a / b)


def conf_table(title, groups, order):
    lines = ["", "**%s**" % title, "", "| group | Alex-present | TP | FP | FN | recall | precision |", "|---|---|---|---|---|---|---|"]
    missed = []
    for g in order:
        if g not in groups:
            continue
        tp, fp, fn, _ = groups[g]
        lines.append("| %s | %d | %d | %d | %d | %s | %s |" % (g, tp + fn, tp, fp, fn, pct(tp, tp + fn), pct(tp, tp + fp)))
        if tp + fn and not tp:
            missed.append(g)
    lines.append("")
    lines.append("Missed entirely (Alex-present > 0, judge TP = 0): %s" % (", ".join(missed) if missed else "none"))
    return lines


def short(s, n=220):
    s = " ".join((s or "").split())
    return s if len(s) <= n else s[:n - 1] + "…"


def verdict(res):
    """(passed, reasons): item agreement at or above the bar and no reach tier or fact type missed entirely."""
    reasons = []
    if len(res["matches"]) < BAR * res["n"]:
        reasons.append("item-level agreement %s is below %d%%" % (pct(len(res["matches"]), res["n"]), int(BAR * 100)))
    for label, groups in (("reach tier", res["by_tier"]), ("fact type", res["by_type"])):
        for g, (tp, _, fn, _) in groups.items():
            if tp + fn and not tp:
                reasons.append("%s %s missed entirely" % (label, g))
    return not reasons, reasons


def three_figures(res):
    n = res["n"]
    L = ["## Three figures", "",
         "| figure | items matching | agreement | status |", "|---|---|---|---|",
         "| strict blind (primary) | %d of %d | %s | Bar %d%%: %s |" % (
             len(res["matches"]), n, pct(len(res["matches"]), n), int(BAR * 100),
             "MET" if len(res["matches"]) >= BAR * n else "NOT MET")]
    for label, k in (("family rule", "fam_matches"), ("family rule plus adjudicated corrections", "corr_matches")):
        if res.get(k) is None:
            L.append("| %s | n/a | n/a | post-hoc, not validation; not run |" % label)
        else:
            L.append("| %s | %d of %d | %s | post-hoc, not validation |" % (label, len(res[k]), n, pct(len(res[k]), n)))
    L += ["", "Family rule: an item matches if the judge's set of families equals Alex's set of families (strength ignored). "
          "Corrected key: Alex's labels with the adjudication rulings applied; judge detections are unchanged. "
          "PASS/FAIL below rests on the strict figure only.", ""]
    return L


def render(res, judge_manifest=None, notice=None):
    n, m = res["n"], len(res["matches"])
    ok = m >= BAR * n
    L = ["# Judge validation report", ""]
    if judge_manifest:
        L.append("Judge run %s, model %s, prompt_hash %s%s." % (
            judge_manifest["run_id"], judge_manifest["judge_model"], judge_manifest["prompt_hash"][:12],
            "" if notice else " (matches the live runs)"))
        L.append("")
    if notice:
        L += ["**PRE-REJUDGE: %s**" % notice, ""]
    L += ["## Item-level agreement", "",
          "%d of %d items match (judge's set of detected rows equals Alex's set, strength ignored): **%s**. Bar: %d%%. **%s**" % (
              m, n, pct(m, n), int(BAR * 100), "MET" if ok else "NOT MET"), "",
          "Non-matching items: %s" % (", ".join(res["mismatch"]) or "none"), "",
          "Judge quotes not found in the text (unverified): %d" % res["unverified"], ""]
    L += three_figures(res)
    L += ["## Row level"]
    L += conf_table("By reach tier", res["by_tier"], TIERS)
    L += conf_table("By fact type", res["by_type"], TYPES)
    s = res["strength"]
    L += ["", "## Strength agreement (rows both Alex and the judge detected)", "", "| type | pairs | agree |", "|---|---|---|"]
    for t in TYPES:
        p, a = s["pairs"][t]
        L.append("| %s | %d | %s |" % (t, p, pct(a, p)))
    tp, ta = sum(v[0] for v in s["pairs"].values()), sum(v[1] for v in s["pairs"].values())
    L += ["", "All types: %d of %d agree (%s). Pairs without a strength from Alex: %d." % (ta, tp, pct(ta, tp), s["no_alex_strength"]),
          "", "| Alex \\ judge | verbatim | paraphrase | pattern |", "|---|---|---|---|"]
    for a in STRENGTHS:
        L.append("| %s | %s |" % (a, " | ".join(str(s["matrix"].get((a, j), 0)) for j in STRENGTHS)))
    L += ["", "## Judge false positives (judge detected, Alex did not): %d" % len(res["fp"]), ""]
    L += ["- %s %s [%s%s]: \"%s\"" % (x["item"], x["row"], x["verdict"], ", quote unverified" if x["unverified"] else "",
                                       short(x["quote"])) for x in res["fp"]] or ["none"]
    L += ["", "## Judge false negatives (Alex labelled, judge did not): %d" % len(res["fn"]), ""]
    for x in res["fn"]:
        src = "inserted sentence: \"%s\"" % short(x["inserted"]) if x["inserted"] else "base content (not inserted)"
        L.append("- %s %s [Alex: %s]: %s%s" % (x["item"], x["row"], x["alex_strength"] or "no strength", src,
                                                 "; Alex's note: %s" % short(x["notes"], 120) if x["notes"] else ""))
    if not res["fn"]:
        L.append("none")
    L += ["", "## Adjudication: Alex versus construction labels (inserted rows)", "",
          "%d items differ on an inserted row: %s" % (len(res["adjudicate_items"]), ", ".join(res["adjudicate_items"]) or "none"), ""]
    L += ["- %s %s: %s (construction: %s%s)" % (x["item"], x["row"], x["what"], x["expected"],
                                               ", Alex: %s" % x["alex"] if x["alex"] else "") for x in res["adjudicate"]] or ["none"]
    L += ["", "### Base content (rows Alex labelled that were not inserted; legitimate labels): %d" % len(res["base_content"]), ""]
    for x in res["base_content"]:
        tag = ("family sibling of inserted %s" % x["family_sibling_of"]) if x["family_sibling_of"] else "base content"
        if x["lookalike_row"]:
            tag = "ROW THE NEAR-MISS RESEMBLES (check the base before treating as Alex's error)"
        L.append("- %s %s: %s" % (x["item"], x["row"], tag))
    if not res["base_content"]:
        L.append("none")
    L += ["", "## Near-miss items", ""]
    for mode in ("literal", "reworded"):
        grp = [x for x in res["near"] if x["mode"] == mode]
        L += ["**%s** (%d items): judge matched Alex on %d; judge detected a row the item resembles on %d; Alex labelled one on %d" % (
            mode, len(grp), sum(x["match"] for x in grp), sum(bool(x["judge_hit_lookalike"]) for x in grp),
            sum(bool(x["alex_hit_lookalike"]) for x in grp)), ""]
        for x in grp:
            L.append("- %s (%s): resembles %s; judge rows %s; Alex rows %s; judge fooled: %s" % (
                x["item"], x["family"], ", ".join(x["resembles"]) or "no registry row", ", ".join(x["judge_rows"]) or "none",
                ", ".join(x["alex_rows"]) or "none", ", ".join(x["judge_hit_lookalike"]) or "no"))
        L.append("")
    passed, reasons = verdict(res)
    L.append("PASS" if passed else "FAIL: " + "; ".join(reasons))
    return "\n".join(L) + "\n"


def run(labels_path, judge_dir, items_path, construction_path, registry_path, scores_root, allow_stub=False,
        families_path=DEFAULT_FAMILIES, adjudication=(), pre_rejudge=False):
    registry = read_jsonl(registry_path)
    items = read_jsonl(items_path)
    ids = [i["id"] for i in items]
    alex = load_alex(labels_path, ids, {r["id"] for r in registry})
    manifest, judgments = check_judge_run(judge_dir, scores_root, items_path, ids, allow_stub, pre_rejudge)
    notice = pre_rejudge_notice(manifest, scores_root) if pre_rejudge else None
    construction = read_jsonl(construction_path)
    jv = judge_view(judgments)
    res = analyze(registry, ids, alex, jv, construction, {i["id"]: i["text"] for i in items})
    r2f = load_families(families_path, [r["id"] for r in registry])
    rulings = parse_adjudication(adjudication, set(ids), r2f) if adjudication else None
    a_rows = {i: alex[i]["rows"] for i in ids}
    res["fam_matches"] = family_agreement(ids, jv, a_rows, r2f)
    res["corr_matches"] = family_agreement(ids, jv, a_rows, r2f, rulings) if rulings is not None else None
    return render(res, manifest, notice), res


# ---------------------------------------------------------------- v2: family units (primary, pre-registered)
# Units are the registry rows with the four families (families.json) collapsed. Alex's labels are unit labels
# (labels_v2.csv from label_tool.html). The judge's row detections are mapped to units. There is no post-hoc
# corrections mode here.

V2_RUN_ID = "validation_v2_20261028"
V2_DIR = os.path.join(HERE, "v2")
V2_STRENGTHS = STRENGTHS + ("unsure",)
STRENGTH_RANK = {"verbatim": 0, "paraphrase": 1, "pattern": 2}


def load_alex_units(path, item_ids, unit_ids):
    """{item: {"units": set, "strength": {unit: s}, "notes": str}}; refuses on any unlabelled or malformed row.
    Columns: item_id, units_present (`;`-joined, `none` for none), strengths (`unit=strength;...`), notes."""
    with open(path, encoding="utf-8", newline="") as f:
        data = list(csv.DictReader(f))
    by = {r["item_id"].strip(): r for r in data if r.get("item_id")}
    missing = [i for i in item_ids if i not in by or not (by[i].get("units_present") or "").strip()]
    if missing:
        raise Refuse("labels not complete: %d of %d items have no units_present (`none` means no units); "
                     "first: %s" % (len(missing), len(item_ids), ", ".join(missing[:5])))
    extra = sorted(set(by) - set(item_ids))
    if extra:
        raise Refuse("labels name unknown items: %s" % ", ".join(extra[:5]))
    out, bad = {}, []
    for i in item_ids:
        r = by[i]
        raw = r["units_present"].strip()
        units = [] if raw.lower() == "none" else [t.strip() for t in raw.split(";") if t.strip()]
        unknown = [t for t in units if t not in unit_ids]
        if unknown or len(set(units)) != len(units):
            bad.append("%s: %s" % (i, unknown or "duplicate units"))
            continue
        strength, wrong = {}, []
        for t in [t.strip() for t in (r.get("strengths") or "").split(";") if t.strip()]:
            k, _, v = t.partition("=")
            k, v = k.strip(), v.strip()
            if k not in units or v not in V2_STRENGTHS:
                wrong.append(t)
            else:
                strength[k] = v
        if wrong:
            bad.append("%s: bad strength entries %s" % (i, wrong))
            continue
        out[i] = {"units": set(units), "strength": strength, "notes": (r.get("notes") or "").strip()}
    if bad:
        raise Refuse("labels malformed:\n  " + "\n  ".join(bad))
    return out


def unit_info(registry, r2f):
    """{unit: {"reach", "type", "rows"}}; families take the reach and type of their rows (identical within a family)."""
    out = {}
    for r in registry:
        u = out.setdefault(r2f[r["id"]], {"reach": r["intended_reach"], "type": r["type"], "rows": []})
        u["rows"].append(r["id"])
    return out


def judge_units(judge, r2f):
    """{item: {unit: strongest verdict among the unit's detected rows}}."""
    out = {}
    for i, rows in judge.items():
        d = {}
        for row, v in rows.items():
            u = r2f[row]
            if u not in d or STRENGTH_RANK[v["verdict"]] < STRENGTH_RANK[d[u]]:
                d[u] = v["verdict"]
        out[i] = d
    return out


def unit_confusion(units, item_ids, alex, jud, key):
    """{group: [TP, FP, FN, TN]} over (item, unit) pairs, grouped by key(unit)."""
    out = {}
    for u in units:
        c = out.setdefault(key(u), [0, 0, 0, 0])
        for i in item_ids:
            a, j = u in alex[i]["units"], u in jud[i]
            c[0 if a and j else 1 if j else 2 if a else 3] += 1
    return out


def analyze_units(registry, r2f, item_ids, alex, jud):
    info = unit_info(registry, r2f)
    units = list(info)
    res = {"n": len(item_ids), "units": units, "info": info}
    res["matches"] = [i for i in item_ids if set(jud[i]) == alex[i]["units"]]
    res["mismatch"] = [i for i in item_ids if i not in res["matches"]]
    res["by_unit"] = unit_confusion(units, item_ids, alex, jud, lambda u: u)
    res["by_tier"] = unit_confusion(units, item_ids, alex, jud, lambda u: info[u]["reach"])
    res["by_type"] = unit_confusion(units, item_ids, alex, jud, lambda u: info[u]["type"])
    pairs, mat, unsure, nostr = {t: [0, 0] for t in TYPES}, {}, 0, 0
    for i in item_ids:
        for u in alex[i]["units"] & set(jud[i]):
            a = alex[i]["strength"].get(u)
            if a is None:
                nostr += 1
            elif a == "unsure":
                unsure += 1
            else:
                pairs[info[u]["type"]][0] += 1
                pairs[info[u]["type"]][1] += int(a == jud[i][u])
                mat[(a, jud[i][u])] = mat.get((a, jud[i][u]), 0) + 1
    res["strength"] = {"pairs": pairs, "matrix": mat, "unsure": unsure, "no_alex_strength": nostr}
    res["diffs"] = [{"item": i, "alex": sorted(alex[i]["units"]), "judge": sorted(jud[i])} for i in res["mismatch"]]
    return res


def construction_figures(res, item_ids, alex, construction, r2f):
    """Read only after labels and the judge run have passed their checks. Adds the label-quality figure and the
    agreement split by base source (N0 vs memory-condition) and by kind."""
    cons = {c["id"]: c for c in construction}
    if sorted(cons) != sorted(item_ids):
        raise Refuse("construction labels do not cover exactly the items")
    inserted, unlabelled = 0, []
    for i in item_ids:
        exp = {r2f[e["row"]] for e in cons[i]["expected"]}
        inserted += len(exp)
        for u in sorted(exp - alex[i]["units"]):
            unlabelled.append({"item": i, "unit": u})
    res["label_quality"] = {"inserted": inserted, "unlabelled": unlabelled}
    match = set(res["matches"])

    def split(keyf):
        g = {}
        for i in item_ids:
            c = g.setdefault(keyf(cons[i]), [0, 0])
            c[0] += int(i in match)
            c[1] += 1
        return g
    res["by_source"] = split(lambda c: "N0" if c["base"]["condition"] == "N0" else "memory-condition")
    res["by_kind"] = split(lambda c: c["kind"])
    return res


def verdict_units(res):
    """(passed, reasons): item agreement at or above the bar and no reach tier or fact type missed entirely."""
    return verdict({"n": res["n"], "matches": res["matches"], "by_tier": res["by_tier"], "by_type": res["by_type"]})


def render_units(res, judge_manifest, notice=None):
    n, m = res["n"], len(res["matches"])
    ok = m >= BAR * n
    L = ["# Judge validation report (v2, family units)", "",
         "Judge run %s, model %s, prompt_hash %s%s." % (
             judge_manifest["run_id"], judge_manifest["judge_model"], judge_manifest["prompt_hash"][:12],
             "" if notice else " (matches the live runs)"), ""]
    if notice:
        L += ["**PRE-REJUDGE: %s**" % notice, ""]
    L += ["## Primary: item agreement on units", "",
          "%d of %d items match (the judge's set of units, rows mapped through families.json, equals Alex's set; "
          "strength ignored): **%s**. Bar: %d%%. **%s**" % (m, n, pct(m, n), int(BAR * 100), "MET" if ok else "NOT MET"), "",
          "Non-matching items: %s" % (", ".join(res["mismatch"]) or "none"), ""]
    for d in res["diffs"]:
        L.append("- %s: Alex {%s}; judge {%s}" % (d["item"], ", ".join(d["alex"]) or "none", ", ".join(d["judge"]) or "none"))
    L += ["", "## Per unit (recall = TP/(TP+FN), precision = TP/(TP+FP))", "",
          "| unit | reach | Alex-present | TP | FP | FN | recall | precision |", "|---|---|---|---|---|---|---|---|"]
    for u in res["units"]:
        tp, fp, fn, _ = res["by_unit"][u]
        L.append("| %s | %s | %d | %d | %d | %d | %s | %s |" % (u, res["info"][u]["reach"], tp + fn, tp, fp, fn,
                                                           pct(tp, tp + fn), pct(tp, tp + fp)))
    L += conf_table("Recall by reach tier", res["by_tier"], TIERS)
    L += conf_table("By fact type", res["by_type"], TYPES)
    if res.get("by_source"):
        L += ["", "## Agreement split (construction labels, read after the checks)", "",
              "| base source | items matching | agreement |", "|---|---|---|"]
        for g in ("N0", "memory-condition"):
            a, b = res["by_source"].get(g, [0, 0])
            L.append("| %s | %d of %d | %s |" % (g, a, b, pct(a, b)))
        L += ["", "| kind | items matching | agreement |", "|---|---|---|"]
        for g, (a, b) in sorted(res["by_kind"].items()):
            L.append("| %s | %d of %d | %s |" % (g, a, b, pct(a, b)))
        q = res["label_quality"]
        L += ["", "## Label quality: inserted units Alex did not label", "",
              "%d of %d inserted units not labelled by Alex%s" % (
                  len(q["unlabelled"]), q["inserted"],
                  (": " + ", ".join("%s %s" % (x["item"], x["unit"]) for x in q["unlabelled"])) if q["unlabelled"] else "")]
    s = res["strength"]
    L += ["", "## Strength agreement (secondary; units both Alex and the judge detected)", "",
          "| type | pairs | agree |", "|---|---|---|"]
    for t in TYPES:
        p, a = s["pairs"][t]
        L.append("| %s | %d | %s |" % (t, p, pct(a, p)))
    tp, ta = sum(v[0] for v in s["pairs"].values()), sum(v[1] for v in s["pairs"].values())
    L += ["", "All types: %d of %d agree (%s). Excluded: %d marked unsure by Alex, %d without a strength." % (
        ta, tp, pct(ta, tp), s["unsure"], s["no_alex_strength"]), "",
        "| Alex \\ judge | verbatim | paraphrase | pattern |", "|---|---|---|---|"]
    for a in STRENGTHS:
        L.append("| %s | %s |" % (a, " | ".join(str(s["matrix"].get((a, j), 0)) for j in STRENGTHS)))
    passed, reasons = verdict_units(res)
    L += ["", "PASS" if passed else "FAIL: " + "; ".join(reasons)]
    return "\n".join(L) + "\n"


def run_units(labels_path, judge_dir, items_path, construction_path, registry_path, scores_root, families_path,
              allow_stub=False, pre_rejudge=False):
    """Order: (1) labels complete, (2) judge run checked, (3) only then the construction labels."""
    registry = read_jsonl(registry_path)
    items = read_jsonl(items_path)
    ids = [i["id"] for i in items]
    r2f = load_families(families_path, [r["id"] for r in registry])
    alex = load_alex_units(labels_path, ids, set(r2f.values()))
    manifest, judgments = check_judge_run(judge_dir, scores_root, items_path, ids, allow_stub, pre_rejudge)
    if manifest.get("set") != "v2" or manifest.get("run_id") != V2_RUN_ID:
        raise Refuse("judge run %s (set %s) is not the v2 validation run %s" % (
            manifest.get("run_id"), manifest.get("set"), V2_RUN_ID))
    notice = pre_rejudge_notice(manifest, scores_root) if pre_rejudge else None
    jud = judge_units(judge_view(judgments), r2f)
    res = analyze_units(registry, r2f, ids, alex, jud)
    construction_figures(res, ids, alex, read_jsonl(construction_path), r2f)
    return render_units(res, manifest, notice), res


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--labels", default=os.path.join(HERE, "labels.csv"))
    ap.add_argument("--judge", default=DEFAULT_JUDGE)
    ap.add_argument("--items", default=os.path.join(HERE, "items.jsonl"))
    ap.add_argument("--construction", default=os.path.join(HERE, "construction", "labels.jsonl"))
    ap.add_argument("--registry", default=os.path.join(ROOT, "registry.jsonl"))
    ap.add_argument("--scores-root", default=os.path.join(ROOT, "scores"))
    ap.add_argument("--families", default=DEFAULT_FAMILIES, help="row id -> family id (post-hoc figures)")
    ap.add_argument("--adjudication", action="append", default=[], metavar="PATH",
                    help="adjudication .md file; repeatable (post-hoc corrected key)")
    ap.add_argument("--allow-stub", action="store_true", help="tests only")
    ap.add_argument("--pre-rejudge", action="store_true",
                    help="report although the live runs carry a different prompt hash; the report says the live runs "
                         "have not been judged under this prompt")
    ap.add_argument("--set", dest="set_name", choices=("v1", "v2"), default="v1",
                    help="v2 (with --family-labels) reads validation/v2 and scores/validation_v2_20261028")
    ap.add_argument("--family-labels", metavar="LABELS_V2.csv",
                    help="v2 family mode: Alex's unit labels from label_tool.html (needs --set v2)")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    if bool(a.family_labels) != (a.set_name == "v2"):
        ap.error("--family-labels and --set v2 go together")
    if a.family_labels:
        if a.adjudication or a.labels != os.path.join(HERE, "labels.csv"):
            ap.error("family mode takes only --family-labels; there is no adjudication mode in v2")
        text, _ = run_units(a.family_labels, a.judge if a.judge != DEFAULT_JUDGE else os.path.join(ROOT, "scores", V2_RUN_ID),
                            a.items if a.items != os.path.join(HERE, "items.jsonl") else os.path.join(V2_DIR, "items.jsonl"),
                            a.construction if a.construction != os.path.join(HERE, "construction", "labels.jsonl")
                            else os.path.join(V2_DIR, "construction", "labels.jsonl"),
                            a.registry, a.scores_root, a.families, a.allow_stub, a.pre_rejudge)
    else:
        text, _ = run(a.labels, a.judge, a.items, a.construction, a.registry, a.scores_root, a.allow_stub,
                      a.families, a.adjudication, a.pre_rejudge)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(text)
    sys.stdout.write(text)


if __name__ == "__main__":
    main()
