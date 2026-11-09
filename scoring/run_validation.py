#!/usr/bin/env python3
"""Run the judge on the 40 validation items (validation/items.jsonl). Python 3.9.

  run_validation.py [--stub] [--max-calls N] [--resume] [--finalize] [--pre-rejudge] [--set v1|v2]

--set v2 runs validation/v2/items.jsonl as run validation_v2_20261028 (scores/validation_v2_20261028/); the
manifest records the set name and the items file and hash. Without --set the behaviour is v1, unchanged.

Reuses the judge/ modules and judge/config.yaml unchanged: same blind row labels (make_labels with the
config seed), same prompt, same verification (process_rows, process_candidates), same live guard,
preflight table and typed yes. No stores, no probe_map scoring. Output: scores/validation_<seed>/.
Without --stub the calls are live (Opus via the claude CLI). --finalize re-derives every output from
the saved calls without a model. The run refuses to start if its prompt hash differs from the hash in
the committed live runs under scores/, because the validation would then not describe that judge.
--pre-rejudge lifts that refusal for a revised prompt whose live runs have not been rejudged yet; the manifest then
carries a notice that the validation is not yet usable as a result for them."""
import argparse
import os
import sys
import time

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "validation"))

import run_judge  # noqa: E402  (Paths, make_backend, git_info, file_hash, resolve_out_dir)
import vlib  # noqa: E402
from judge import firmexport  # noqa: E402
from judge.build_prompt import PromptBuilder, make_labels  # noqa: E402
from judge.llm import (JudgeClient, LiveGuardError, LLMError, MaxCallsExceeded, confirm_live,  # noqa: E402
                       live_guard, preflight_table)
from judge.util import (iso_now, read_json, read_jsonl, sha256_text, write_json, write_jsonl,  # noqa: E402
                        write_text)
from judge.validate import Invalid, validate  # noqa: E402
from judge.verify import FirmIndex, process_candidates, process_rows  # noqa: E402


# Validation sets. v1 (default) takes its run id from the judge config's shuffle seed; v2 has a fixed run id.
SETS = {"v1": {"items": os.path.join("validation", "items.jsonl"), "run_id": None},
        "v2": {"items": os.path.join("validation", "v2", "items.jsonl"), "run_id": "validation_v2_20261028"}}


def run_id_for(cfg, set_name="v1"):
    if SETS[set_name]["run_id"]:
        return SETS[set_name]["run_id"]
    return "validation_%d" % cfg["shuffle_seed"]


def call_id(run_id, item_id):
    return sha256_text("%s|item|%s" % (run_id, item_id))[:16]


def load_items(path):
    items = read_jsonl(path)
    ids = [i["id"] for i in items]
    if not items or len(set(ids)) != len(ids) or any(set(i) != {"id", "text"} for i in items):
        raise SystemExit("%s must hold unique {id, text} rows and nothing else" % path)
    return items


PRE_REJUDGE_NOTICE = ("The live runs were judged under prompt hash %s, not under this prompt (%s). They have not "
                      "been judged under this prompt, and this validation is not yet usable as a result for them.")


def check_against_live(paths, prefix_hash, out):
    """The prompt hash and the firm export must match the committed live runs (unless paths.pre_rejudge is set,
    which lets a differing hash through and returns a notice for the report and manifest)."""
    live = vlib.live_manifests(paths.scores_root)
    if not live:
        raise SystemExit("no committed live runs under %s to check the prompt hash against" % paths.scores_root)
    bad = sorted({m["prompt_hash"] for m in live if m["prompt_hash"] != prefix_hash})
    notice = None
    if bad and not getattr(paths, "pre_rejudge", False):
        raise SystemExit("prompt hash %s differs from the live runs' %s; the validation would not describe "
                         "that judge. Nothing was run." % (prefix_hash[:12], ", ".join(h[:12] for h in bad)))
    if bad:
        notice = PRE_REJUDGE_NOTICE % (", ".join(h[:12] for h in bad), prefix_hash[:12])
        out("PRE-REJUDGE: " + notice)
    firm = None
    if paths.check_firm:
        fams = {repr(m["source_run"]["firm"]) for m in live}
        if len(fams) != 1:
            raise SystemExit("the live runs disagree on the firm export; cannot check it")
        problems, firm = firmexport.check_against_manifest(paths.firm_dir, paths.firm_tag,
                                                           {"firm": live[0]["source_run"]["firm"]})
        if problems:
            raise SystemExit("firm export does not match the live runs:\n  " + "\n  ".join(problems))
    if not bad:
        out("prompt hash %s matches %d live runs" % (prefix_hash[:12], len(live)))
    return firm, notice


def prepare(paths, cfg, resume, out, existing=False):
    items = load_items(paths.items)
    registry = read_jsonl(paths.registry)
    near = open(paths.near_misses, encoding="utf-8").read()
    template = open(paths.prompt, encoding="utf-8").read()
    labels = make_labels(registry, cfg["shuffle_seed"])
    pb = PromptBuilder(registry, near, labels, template)
    firm, notice = check_against_live(paths, pb.prefix_hash, out) if getattr(paths, "check_live", True) else (None, None)
    rid = run_id_for(cfg, getattr(paths, "set_name", "v1"))
    if existing:
        out_dir = os.path.join(paths.scores_root, rid)
        if not os.path.isdir(out_dir):
            raise SystemExit("%s does not exist; nothing to finalize" % out_dir)
        return {"items": items, "registry": registry, "labels": labels, "pb": pb, "out_dir": out_dir,
                "run_id": rid, "todo": [], "firm": firm, "near": near, "notice": notice}
    out_dir = run_judge.resolve_out_dir(paths.scores_root, rid, resume)
    calls = {call_id(rid, i["id"]): i["id"] for i in items}
    write_json(os.path.join(out_dir, "blind_map.json"), {
        "run_id": rid, "shuffle_seed": cfg["shuffle_seed"], "prefix_hash": pb.prefix_hash,
        "labels": {v: k for k, v in labels.items()}, "calls": calls})
    cfg_dir = os.path.join(out_dir, "config")
    write_text(os.path.join(cfg_dir, "config.yaml"), open(paths.config, encoding="utf-8").read())
    write_text(os.path.join(cfg_dir, "judge.md"), template)
    write_text(os.path.join(cfg_dir, "near_misses.md"), near)
    write_text(os.path.join(cfg_dir, "items.jsonl"), open(paths.items, encoding="utf-8").read())
    if not os.path.exists(os.path.join(out_dir, "manifest.json")):
        write_json(os.path.join(out_dir, "manifest.json"), {"run_id": rid, "status": "incomplete"})
    todo = [i for i in items if not os.path.exists(os.path.join(out_dir, "calls", call_id(rid, i["id"]) + ".json"))]
    return {"items": items, "registry": registry, "labels": labels, "pb": pb, "out_dir": out_dir, "run_id": rid,
            "todo": todo, "firm": firm, "near": near, "notice": notice}


def finalize(paths, cfg, prep, client, stopped, model, stub):
    registry, labels, out_dir, rid = prep["registry"], prep["labels"], prep["out_dir"], prep["run_id"]
    index = FirmIndex(firmexport.firm_docs(paths.firm_dir), cfg["trace"]["shingle"])
    judgments, lexical, dis, cands, cands_rej, missing = [], [], [], [], [], []
    dropped = 0
    for it in prep["items"]:
        cid = call_id(rid, it["id"])
        p = os.path.join(out_dir, "calls", cid + ".json")
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
        base = {"run_id": rid, "item_id": it["id"], "call_id": cid}
        judgments.append(dict(base, rows=rows, candidates=ok, text_sha256=sha256_text(it["text"])))
        lexical.append(dict(base, hits=lex))
        dis += [dict(base, **x) for x in d]
        cands += [dict(base, **c) for c in ok]
        cands_rej += [dict(base, **c) for c in rej]
    write_jsonl(os.path.join(out_dir, "judgments.jsonl"), judgments)
    write_jsonl(os.path.join(out_dir, "lexical.jsonl"), lexical)
    write_jsonl(os.path.join(out_dir, "disagreements.jsonl"), dis)
    write_jsonl(os.path.join(out_dir, "candidates.jsonl"), cands)
    write_jsonl(os.path.join(out_dir, "candidates_rejected.jsonl"), cands_rej)
    all_rows = [r for j in judgments for r in j["rows"]]
    expected = len(prep["items"])
    write_json(os.path.join(out_dir, "manifest.json"), {
        "run_id": rid, "kind": "validation", "status": "complete" if not missing and not stopped else "incomplete",
        "stopped": stopped, "missing_calls": missing, "created": iso_now(), "stub": bool(stub),
        "judge_model": model, "backend": "stub" if stub else cfg["roles"]["judge"]["backend"],
        "prompt_hash": prep["pb"].prefix_hash, "judge_md_hash": run_judge.file_hash(paths.prompt),
        "near_misses_hash": run_judge.file_hash(paths.near_misses), "registry_hash": run_judge.file_hash(paths.registry),
        "set": getattr(paths, "set_name", "v1"), "items_file": SETS[getattr(paths, "set_name", "v1")]["items"],
        "items_hash": run_judge.file_hash(paths.items), "config_hash": run_judge.file_hash(paths.config),
        "scoring_git": run_judge.git_info(paths.repo_dir), "rejected_calls": client.count_rejected(),
        "dropped_unknown_keys": dropped, "firm_export": prep["firm"],
        "pre_rejudge": prep["notice"] is not None, "pre_rejudge_notice": prep["notice"],
        "calls": {"expected": expected, "saved": expected - len(missing), "made_this_session": client.made},
        "shuffle_seed": cfg["shuffle_seed"], "trace": cfg["trace"],
        "counts": {"judgments": len(judgments),
                   "exact_match_overrides": sum(1 for r in all_rows if r["override"] and r["override"].startswith("exact")),
                   "verbatim_demoted": sum(1 for r in all_rows if r["override"] == "verbatim_demoted"),
                   "quote_unverified": sum(1 for r in all_rows if r["quote_unverified"]),
                   "disagreements": len(dis), "candidates": len(cands), "candidates_rejected": len(cands_rej)}})


def run(paths=None, stub=False, max_calls=None, resume=False, finalize_only=False, input_fn=input, environ=None,
        backend=None, runner=None, out=print):
    paths = paths or default_paths()
    cfg = yaml.safe_load(open(paths.config, encoding="utf-8"))
    environ = os.environ if environ is None else environ
    if not stub and not finalize_only:
        try:
            live_guard(paths.repo_dir, environ)
        except (LiveGuardError, LLMError) as e:
            raise SystemExit("live guard: %s" % e)
    prep = prepare(paths, cfg, resume, out, existing=finalize_only)
    cwd, stopped = None, None
    if finalize_only:
        client, model = JudgeClient(None, "none", prep["run_id"], prep["out_dir"]), "none"
    else:
        be, model, cwd = (backend, "stub", None) if backend else run_judge.make_backend(cfg, stub, environ, runner)
        model = "stub" if stub else cfg["roles"]["judge"]["model"]
        rows = [("validation items", len(prep["todo"]), sum(len(prep["pb"].build(i["text"])) for i in prep["todo"]))]
        out(preflight_table(rows, model, "stub" if stub else cfg["roles"]["judge"]["backend"]))
        if not stub and prep["todo"] and not confirm_live(input_fn):
            raise SystemExit("not confirmed; no calls made")
        client = JudgeClient(be, model, prep["run_id"], prep["out_dir"], max_calls=max_calls,
                             retry_sleep=cfg["claude_cli"]["retry_sleep_s"], sleep=time.sleep)
        try:
            for it in prep["items"]:
                client.call(call_id(prep["run_id"], it["id"]), prep["pb"].build(it["text"]),
                            lambda t, L=list(prep["labels"].values()): validate(t, L), "judge_validation", "V")
        except MaxCallsExceeded as e:
            stopped = str(e)
        finally:
            if cwd:
                import shutil
                shutil.rmtree(cwd, ignore_errors=True)
    finalize(paths, cfg, prep, client, stopped, model, stub)
    out("%s: %s" % (prep["run_id"], prep["out_dir"]))
    return prep["out_dir"]


def default_paths(set_name="v1"):
    return run_judge.Paths(items=os.path.join(HERE, SETS[set_name]["items"]), check_live=True, set_name=set_name)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stub", action="store_true")
    ap.add_argument("--max-calls", type=int)
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--finalize", action="store_true", help="re-derive outputs from saved calls, no model")
    ap.add_argument("--pre-rejudge", action="store_true",
                    help="allow a prompt hash that differs from the live runs'; the manifest then says the live runs "
                         "have not been judged under this prompt")
    ap.add_argument("--set", dest="set_name", choices=sorted(SETS), default="v1",
                    help="validation set: v1 (default, validation/items.jsonl) or v2 (validation/v2/items.jsonl, "
                         "run validation_v2_20261028)")
    a = ap.parse_args(argv)
    paths = default_paths(a.set_name)
    paths.pre_rejudge = a.pre_rejudge
    run(paths=paths, stub=a.stub, max_calls=a.max_calls, resume=a.resume, finalize_only=a.finalize)


if __name__ == "__main__":
    main()
