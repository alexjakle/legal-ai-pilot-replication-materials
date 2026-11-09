#!/usr/bin/env python3
"""Judge and score pipeline run folders (read-only on ../pipeline). Python 3.9.

  run_judge.py judge  RUN_DIR... [--stub] [--repeat] [--max-calls N] [--resume] [--name N]
  run_judge.py finalize RUN_DIR SCORES_DIR      re-derive every output from saved calls (no model)
  run_judge.py report SCORES_DIR... [--name N]  combined report across scored runs

`judge` with several RUN_DIRs scores them all and writes one combined report. Without --stub the calls
are live: git/API-key guard, preflight table, typed yes.
"""
import argparse
import math
import os
import subprocess
import sys
import time

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import report as report_mod  # noqa: E402
import sampler  # noqa: E402
import scorer  # noqa: E402
from judge import firmexport  # noqa: E402
from judge.build_prompt import PromptBuilder, make_labels  # noqa: E402
from judge.llm import (ClaudeCliBackend, JudgeClient, LiveGuardError, LLMError, MaxCallsExceeded,  # noqa: E402
                       confirm_live, live_guard, make_workdir, preflight_table)
from judge.stub import StubBackend  # noqa: E402
from judge.util import (iso_now, norm, read_json, read_jsonl, sha256_bytes, sha256_text,  # noqa: E402
                        write_json, write_jsonl, write_text)
from judge.validate import Invalid, validate  # noqa: E402
from judge.verify import FirmIndex, process_candidates, process_rows  # noqa: E402

STORES = ("client_A", "client_B", "client_C", "firm")
LEXICAL_ONLY = ("matter_only", "discarded")


class Paths(object):
    def __init__(self, **kw):
        self.registry = os.path.join(HERE, "registry.jsonl")
        self.probe_map = os.path.join(HERE, "probe_map.jsonl")
        self.near_misses = os.path.join(HERE, "near_misses.md")
        self.config = os.path.join(HERE, "judge", "config.yaml")
        self.prompt = os.path.join(HERE, "judge", "prompts", "judge.md")
        self.firm_dir = os.path.join(HERE, "..", "pipeline", "data", "firm")
        self.firm_tag = os.path.join(HERE, "..", "pipeline", "data", "FIRM_TAG")
        self.scores_root = os.path.join(HERE, "scores")
        self.repo_dir = HERE
        self.check_firm = True
        self.__dict__.update(kw)


# ---------------------------------------------------------------- inputs

def load_run(run_dir):
    m = read_json(os.path.join(run_dir, "manifest.json"))
    outputs = read_jsonl(os.path.join(run_dir, "probe_outputs.jsonl"))
    if not outputs:
        raise SystemExit("%s has no probe_outputs.jsonl rows; not a scoreable run" % run_dir)
    sdir = os.path.join(run_dir, "stores")
    stores, aux = {}, {}
    for name in STORES:
        rows = read_jsonl(os.path.join(sdir, name + ".jsonl"))
        stores[name] = "\n\n".join(r["text"] for r in rows)
    for name in sorted(f[:-6] for f in os.listdir(sdir) if f.endswith(".jsonl")):
        if name in LEXICAL_ONLY or name in STORES:
            aux[name] = "\n\n".join(r["text"] for r in read_jsonl(os.path.join(sdir, name + ".jsonl")))
    for o in outputs:
        if o["run_id"] != m["run_id"] or o["condition"] != m["condition"]:
            raise SystemExit("probe_outputs row disagrees with manifest in %s" % run_dir)
    return {"dir": run_dir, "manifest": m, "run_id": m["run_id"], "condition": m["condition"],
            "outputs": outputs, "stores": stores, "all_stores": aux}


def call_id(run_id, kind, item_id, repeat=False):
    return sha256_text("%s|%s|%s" % (run_id, kind, item_id))[:16] + ("_r2" if repeat else "")


def build_items(run, subset):
    items = []
    for o in run["outputs"]:
        items.append({"kind": "probe", "item_id": o["probe_id"], "text": o["text"], "repeat": False})
    for s in STORES:
        items.append({"kind": "store", "item_id": s, "text": run["stores"][s], "repeat": False})
    for o in run["outputs"]:
        if o["probe_id"] in subset.get(run["condition"], []):
            items.append({"kind": "probe", "item_id": o["probe_id"], "text": o["text"], "repeat": True})
    for it in items:
        it["call_id"] = call_id(run["run_id"], it["kind"], it["item_id"], it["repeat"])
    return items


def resolve_out_dir(scores_root, run_id, resume):
    base = os.path.join(scores_root, run_id)
    n, cur = 1, base
    while os.path.exists(cur):
        mpath = os.path.join(cur, "manifest.json")
        status = read_json(mpath).get("status") if os.path.exists(mpath) else "incomplete"
        if status != "complete":
            if resume:
                return cur
            raise SystemExit("%s exists and is incomplete; use --resume to continue it" % cur)
        n += 1
        cur = "%s__%d" % (base, n)
    os.makedirs(cur)
    return cur


def git_info(repo_dir):
    def run(*a):
        return subprocess.run(["git"] + list(a), cwd=repo_dir, capture_output=True, text=True).stdout.strip()
    return {"commit": run("rev-parse", "HEAD"),
            "dirty": bool(run("status", "--porcelain", "--", ".", ":(exclude)scores"))}


def file_hash(path):
    with open(path, "rb") as f:
        return sha256_bytes(f.read())


# ---------------------------------------------------------------- prepare / execute

def prepare(run_dir, paths, cfg, repeat, resume):
    run = load_run(run_dir)
    registry = read_jsonl(paths.registry)
    near = open(paths.near_misses, encoding="utf-8").read()
    firm_info = None
    if paths.check_firm:
        problems, firm_info = firmexport.check_against_manifest(paths.firm_dir, paths.firm_tag, run["manifest"])
        if problems:
            raise SystemExit("firm export does not match the run:\n  " + "\n  ".join(problems))
    labels = make_labels(registry, cfg["shuffle_seed"])
    template = open(paths.prompt, encoding="utf-8").read()
    pb = PromptBuilder(registry, near, labels, template)
    pids = sorted(o["probe_id"] for o in run["outputs"])
    plan = sampler.sample(pids, cfg["repeat"]["per_condition"], cfg["repeat"]["seed"]) if repeat else {}
    items = build_items(run, plan)
    out_dir = resolve_out_dir(paths.scores_root, run["run_id"], resume)
    # blind map and subset are written before any call
    write_json(os.path.join(out_dir, "blind_map.json"), {
        "run_id": run["run_id"], "shuffle_seed": cfg["shuffle_seed"], "prefix_hash": pb.prefix_hash,
        "labels": {v: k for k, v in labels.items()},
        "calls": {it["call_id"]: {"kind": it["kind"], "item_id": it["item_id"], "repeat": it["repeat"]}
                  for it in items}})
    if repeat:
        write_json(os.path.join(out_dir, "repeat_subset.json"), {
            "seed": cfg["repeat"]["seed"], "per_condition": cfg["repeat"]["per_condition"],
            "plan": plan, "this_run": {"condition": run["condition"], "probe_ids": plan.get(run["condition"], [])}})
    cfg_dir = os.path.join(out_dir, "config")
    write_text(os.path.join(cfg_dir, "config.yaml"), open(paths.config, encoding="utf-8").read())
    write_text(os.path.join(cfg_dir, "judge.md"), template)
    write_text(os.path.join(cfg_dir, "near_misses.md"), near)
    if not os.path.exists(os.path.join(out_dir, "manifest.json")):
        write_json(os.path.join(out_dir, "manifest.json"), {"run_id": run["run_id"], "status": "incomplete"})
    todo = [it for it in items if not os.path.exists(os.path.join(out_dir, "calls", it["call_id"] + ".json"))]
    return {"run": run, "registry": registry, "labels": labels, "pb": pb, "items": items, "out_dir": out_dir,
            "todo": todo, "firm_info": firm_info, "near": near}


def make_backend(cfg, stub, environ, runner=None):
    if stub:
        return StubBackend(), "stub", None
    rc = cfg["roles"]["judge"]
    if rc["backend"] != "claude_cli":
        raise SystemExit("backend %r is not implemented in the judge" % rc["backend"])
    cwd = make_workdir()
    cc = cfg["claude_cli"]
    return (ClaudeCliBackend(rc["model"], cc["system_prompt"], cc["timeout_s"], runner=runner, environ=environ,
                             cwd=cwd), rc["model"], cwd)


def run_many(run_dirs, paths=None, stub=False, repeat=False, max_calls=None, resume=False, name=None,
             input_fn=input, environ=None, backend=None, runner=None, out=print):
    paths = paths or Paths()
    cfg = yaml.safe_load(open(paths.config, encoding="utf-8"))
    environ = os.environ if environ is None else environ
    if not stub:
        try:
            live_guard(paths.repo_dir, environ)
        except (LiveGuardError, LLMError) as e:
            raise SystemExit("live guard: %s" % e)
    preps = [prepare(d, paths, cfg, repeat, resume) for d in run_dirs]
    model = "stub" if stub else cfg["roles"]["judge"]["model"]
    rows = []
    for p in preps:
        todo = p["todo"]
        for kind in ("probe", "store"):
            sel = [it for it in todo if it["kind"] == kind]
            rows.append(("%s %s" % (p["run"]["condition"], kind), len(sel),
                         sum(len(p["pb"].build(it["text"])) for it in sel)))
    out(preflight_table(rows, model, "stub" if stub else cfg["roles"]["judge"]["backend"]))
    if not stub and sum(r[1] for r in rows):
        if not confirm_live(input_fn):
            raise SystemExit("not confirmed; no calls made")
    remaining = max_calls
    out_dirs = []
    for p in preps:
        be, mname, cwd = (backend, "stub", None) if backend else make_backend(cfg, stub, environ, runner)
        client = JudgeClient(be, mname, p["run"]["run_id"], p["out_dir"], max_calls=remaining,
                             retry_sleep=cfg["claude_cli"]["retry_sleep_s"], sleep=time.sleep)
        stopped = None
        try:
            for it in p["items"]:
                stage = "judge_" + it["kind"]
                client.call(it["call_id"], p["pb"].build(it["text"]),
                            lambda t, L=list(p["labels"].values()): validate(t, L), stage, p["run"]["condition"])
        except MaxCallsExceeded as e:
            stopped = str(e)
        finally:
            if cwd:
                import shutil
                shutil.rmtree(cwd, ignore_errors=True)
        if remaining is not None:
            remaining = max(0, remaining - client.made)
        finalize(p["run"], p["out_dir"], paths, cfg, p, client, stopped, mname, stub)
        out_dirs.append(p["out_dir"])
        out("%s: %s" % (p["run"]["run_id"], p["out_dir"]))
    if len(out_dirs) > 1 or name:
        out(combine(out_dirs, paths, name))
    return out_dirs


# ---------------------------------------------------------------- finalize

def lexical_fate(run, registry):
    rows = []
    for store, text in sorted(run["all_stores"].items()):
        nt = norm(text)
        for r in registry:
            keys = r["detection_keys"]
            hits = [k for k in keys if norm(k) in nt]
            exact = norm(r["text"]) in nt
            need = 1 if r["type"] == "verbatim" else int(math.ceil(len(keys) / 2.0))
            rows.append({"run_id": run["run_id"], "condition": run["condition"], "store": store,
                         "registry_id": r["id"], "intended_reach": r["intended_reach"], "exact_match": exact,
                         "key_hits": hits, "n_keys": len(keys), "lexical_hit": bool(exact or len(hits) >= need),
                         "method": "lexical"})
    return rows


def finalize(run, out_dir, paths, cfg, prep, client, stopped, model, stub):
    registry = prep["registry"]
    labels = prep["labels"]
    reg = {r["id"]: r for r in registry}
    pm = {r["id"]: r for r in read_jsonl(paths.probe_map)}
    docs = firmexport.firm_docs(paths.firm_dir)
    index = FirmIndex(docs, cfg["trace"]["shingle"])
    bmap = read_json(os.path.join(out_dir, "blind_map.json"))
    texts = {it["call_id"]: it for it in prep["items"]}
    outs = {o["probe_id"]: o for o in run["outputs"]}
    rid, cond = run["run_id"], run["condition"]
    judgments, lexical, dis, cands, cands_rej, missing = [], [], [], [], [], []
    store_cands, flag_notes = [], []
    dropped = 0
    for cid, meta in sorted(bmap["calls"].items()):
        p = os.path.join(out_dir, "calls", cid + ".json")
        it = texts[cid]
        if not os.path.exists(p):
            missing.append(cid)
            continue
        try:
            parsed = validate(read_json(p)["text"], list(labels.values()))
        except Invalid:
            missing.append(cid)
            continue
        dropped += parsed.pop("_dropped_keys", 0)
        rows, lex, d = process_rows(parsed, it["text"], registry, labels)
        ok, rej = process_candidates(parsed, it["text"], index, cfg["trace"]["min_score"])
        tap = it["item_id"] if it["kind"] == "probe" else "store:" + it["item_id"]
        base = {"run_id": rid, "condition": cond, "call_id": cid, "tap": tap, "kind": it["kind"],
                "repeat": it["repeat"]}
        judgments.append(dict(base, rows=rows, candidates=ok, text_sha256=sha256_text(it["text"])))
        lexical.append(dict(base, hits=lex))
        dis += [dict(base, **x) for x in d]
        if not it["repeat"]:
            if it["kind"] == "probe":
                cands += [dict(base, **c) for c in ok]
                cands_rej += [dict(base, **c) for c in rej]
            else:
                store_cands += [dict(base, **c) for c in ok]
    primary = [j for j in judgments if not j["repeat"]]
    scores, store_scores, row_scores = [], [], []
    for j in primary:
        verd = {r["registry_id"]: r["verdict"] for r in j["rows"]}
        if j["kind"] == "probe":
            o = outs[j["tap"]]
            quotes = {r["registry_id"]: r["quote"] for r in j["rows"] if r["verdict"] != "absent"}
            s = scorer.score_probe(verd, {"probe_id": o["probe_id"], "new_matter": o["new_matter"]},
                                   pm[o["probe_id"]], registry, quotes=quotes)
            s.update(run_id=rid, condition=cond)
            # annotation goes to its own file so scores.jsonl keeps its shape
            note = s.pop("flag_same_quote")
            if note:
                flag_notes.append({"run_id": rid, "condition": cond, "probe_id": o["probe_id"], "same_quote": note})
            scores.append(s)
        else:
            s = scorer.score_store(j["tap"].split(":", 1)[1], verd, registry)
            s.update(run_id=rid, condition=cond)
            store_scores.append(s)
        for r in j["rows"]:
            rt = reg[r["registry_id"]]["type"]
            row_scores.append({
                "run_id": rid, "condition": cond, "tap": j["tap"], "reader": "judge:" + model,
                "registry_id": r["registry_id"],
                "status": {"absent": "absent", "verbatim": "verbatim"}.get(r["verdict"], "paraphrased"),
                "method": "deterministic" if rt == "verbatim" else "judge",
                "judge_verdict": r["judge_verdict"], "verdict": r["verdict"], "override": r["override"]})
    # consistency (judge's own verdicts, first vs second pass)
    first = {(j["tap"], r["registry_id"]): r["judge_verdict"] for j in primary for r in j["rows"]}
    second = {(j["tap"], r["registry_id"]): r["judge_verdict"] for j in judgments if j["repeat"] for r in j["rows"]}
    cons = scorer.consistency({k: v for k, v in first.items() if k in second}, second) if second else None
    if cons:
        write_json(os.path.join(out_dir, "consistency.json"), cons)
    write_jsonl(os.path.join(out_dir, "judgments.jsonl"), judgments)
    write_jsonl(os.path.join(out_dir, "lexical.jsonl"), lexical)
    write_jsonl(os.path.join(out_dir, "disagreements.jsonl"), dis)
    write_jsonl(os.path.join(out_dir, "candidates.jsonl"), cands)
    write_jsonl(os.path.join(out_dir, "candidates_rejected.jsonl"), cands_rej)
    write_jsonl(os.path.join(out_dir, "store_candidates.jsonl"), store_cands)
    write_jsonl(os.path.join(out_dir, "flag_annotations.jsonl"), flag_notes)
    write_jsonl(os.path.join(out_dir, "scores.jsonl"), scores)
    write_jsonl(os.path.join(out_dir, "row_scores.jsonl"), row_scores)
    write_jsonl(os.path.join(out_dir, "store_scores.jsonl"), store_scores)
    write_jsonl(os.path.join(out_dir, "lexical_fate.jsonl"), lexical_fate(run, registry))
    expected = len(prep["items"])
    complete = not missing and not stopped
    rm = run["manifest"]
    all_rows = [r for j in primary for r in j["rows"]]
    manifest = {
        "run_id": rid, "condition": cond, "status": "complete" if complete else "incomplete",
        "stopped": stopped, "missing_calls": missing, "created": iso_now(), "stub": bool(stub),
        "judge_model": model, "backend": "stub" if stub else cfg["roles"]["judge"]["backend"],
        "prompt_hash": prep["pb"].prefix_hash, "judge_md_hash": file_hash(paths.prompt),
        "near_misses_hash": file_hash(paths.near_misses), "registry_hash": file_hash(paths.registry),
        "probe_map_hash": file_hash(paths.probe_map), "config_hash": file_hash(paths.config),
        "scoring_git": git_info(paths.repo_dir),
        "rejected_calls": client.count_rejected(), "dropped_unknown_keys": dropped,
        "calls": {"expected": expected, "saved": expected - len(missing), "made_this_session": client.made},
        "source_run": {"config_hash": rm.get("config_hash"), "prompts_hash": rm.get("prompts_hash"),
                       "pipeline_git": rm.get("pipeline_git"), "firm": rm.get("firm")},
        "firm_export": prep["firm_info"],
        "shuffle_seed": cfg["shuffle_seed"], "trace": cfg["trace"],
        "counts": {"judgments": len(judgments), "exact_match_overrides": sum(1 for r in all_rows if r["override"] and r["override"].startswith("exact")),
                   "verbatim_demoted": sum(1 for r in all_rows if r["override"] == "verbatim_demoted"),
                   "quote_unverified": sum(1 for r in all_rows if r["quote_unverified"]),
                   "disagreements": len(dis), "candidates": len(cands), "store_candidates": len(store_cands), "candidates_untraced": sum(1 for c in cands if c["untraced"]),
                   "candidates_rejected": len(cands_rej)},
    }
    write_json(os.path.join(out_dir, "manifest.json"), manifest)
    report_mod.write_report([out_dir], registry, os.path.join(out_dir, "report.md"), "Run %s (%s)" % (rid, cond))


def combine(score_dirs, paths, name=None):
    registry = read_jsonl(paths.registry)
    name = name or time.strftime("combined_%Y%m%dT%H%M%S")
    d = os.path.join(paths.scores_root, "_combined", name)
    if os.path.exists(d):
        raise SystemExit("%s already exists; choose another --name" % d)
    os.makedirs(d)
    write_json(os.path.join(d, "sources.json"), {"score_dirs": [os.path.abspath(x) for x in score_dirs]})
    report_mod.write_report(score_dirs, registry, os.path.join(d, "report.md"), "Combined report: " + name)
    return os.path.join(d, "report.md")


def refinalize(run_dir, out_dir, paths=None):
    paths = paths or Paths()
    cfg = yaml.safe_load(open(paths.config, encoding="utf-8"))
    run = load_run(run_dir)
    registry = read_jsonl(paths.registry)
    labels = {v: k for k, v in read_json(os.path.join(out_dir, "blind_map.json"))["labels"].items()}
    labels = {k: v for k, v in labels.items()}
    bmap = read_json(os.path.join(out_dir, "blind_map.json"))
    pb = PromptBuilder(registry, open(paths.near_misses, encoding="utf-8").read(), labels,
                       open(paths.prompt, encoding="utf-8").read())
    items = []
    for cid, m in bmap["calls"].items():
        text = (run["stores"][m["item_id"]] if m["kind"] == "store"
                else next(o["text"] for o in run["outputs"] if o["probe_id"] == m["item_id"]))
        items.append({"call_id": cid, "kind": m["kind"], "item_id": m["item_id"], "repeat": m["repeat"], "text": text})
    model = read_json(os.path.join(out_dir, "manifest.json")).get("judge_model", "unknown")
    stub = model == "stub"
    be = StubBackend()
    client = JudgeClient(be, model, run["run_id"], out_dir)
    finalize(run, out_dir, paths, cfg, {"registry": registry, "labels": labels, "pb": pb, "items": items,
                                        "firm_info": None}, client, None, model, stub)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    j = sub.add_parser("judge")
    j.add_argument("run_dirs", nargs="+")
    j.add_argument("--stub", action="store_true")
    j.add_argument("--repeat", action="store_true")
    j.add_argument("--max-calls", type=int)
    j.add_argument("--resume", action="store_true")
    j.add_argument("--name")
    f = sub.add_parser("finalize")
    f.add_argument("run_dir")
    f.add_argument("scores_dir")
    r = sub.add_parser("report")
    r.add_argument("scores_dirs", nargs="+")
    r.add_argument("--name")
    a = ap.parse_args(argv)
    if a.cmd == "judge":
        run_many(a.run_dirs, stub=a.stub, repeat=a.repeat, max_calls=a.max_calls, resume=a.resume, name=a.name)
    elif a.cmd == "finalize":
        refinalize(a.run_dir, a.scores_dir)
    else:
        print(combine(a.scores_dirs, Paths(), a.name))


if __name__ == "__main__":
    main()
