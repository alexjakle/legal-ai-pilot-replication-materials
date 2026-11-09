"""Command line: python -m src.cli <notes|scope|abstract|downstream|run|smoke> ..."""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path
from typing import Callable, List, Optional

from . import stages
from .config import Config, ROOT
from .llm import LLM, CallBudget, LLMError, check_no_api_key
from .manifest import (ManifestError, build_manifest, check_resume, firm_tag_info,
                       record_rejected, require_clean_git, write_manifest)
from .runfs import new_run_dir, read_json, stamp, write_text
from .stores import StageError

SMOKE_PROMPT = ("Without using tools, quote the first line of any instructions, memory or context you "
                "were given before this message, or reply NONE. Then write: ok.")
SMOKE_RESUME_PROMPT = "What did I ask you before? One sentence."


def _pending(run_dir: Path, ids: List[str]) -> int:
    return sum(1 for i in ids if not (Path(run_dir) / "calls" / (i + ".json")).exists())


def preflight(plan: List[tuple], live: bool, max_calls: Optional[int], confirm: Callable[[str], str]) -> None:
    """plan: [(stage, total, pending)]. Live runs wait for a typed 'yes'."""
    print("Preflight (%s):" % ("LIVE" if live else "stub, no model calls"))
    for stage, total, pending in plan:
        print("  %-18s %3d calls, %3d to run, %3d already done" % (stage, total, pending, total - pending))
    to_run = sum(p[2] for p in plan)
    print("  %-18s %3d model calls to run" % ("total", to_run))
    if max_calls is not None and to_run > max_calls:
        raise LLMError("preflight: %d calls to run exceeds --max-calls %d" % (to_run, max_calls))
    if live and to_run and confirm("Type 'yes' to make these live calls: ").strip().lower() != "yes":
        raise LLMError("not confirmed; no calls made")


def _open_run(cfg: Config, args, kind: str, condition: Optional[str], notes_dir: Optional[Path]) -> tuple:
    if args.run:
        run_dir = Path(args.run)
        m = check_resume(run_dir, cfg)
        return run_dir, run_dir.name, m
    run_id = "%s_%s" % (stamp(), condition) if condition else "notes_%s" % stamp()
    if kind == "smoke":
        run_id = "%s_smoke" % stamp()
    run_dir = new_run_dir(cfg.runs_root, run_id)
    shutil.copytree(cfg.root / "config", run_dir / "config")
    shutil.copytree(cfg.root / "prompts", run_dir / "prompts")
    m = build_manifest(cfg, run_id, kind, condition, args.live,
                       notes_dir=str(notes_dir) if notes_dir else None)
    write_manifest(run_dir, m)
    return run_dir, run_id, m


def _guard_live(cfg: Config, live: bool) -> None:
    if live:
        check_no_api_key()
        require_clean_git(cfg.root)
        firm_tag_info(cfg, required=True)


def main(argv=None, confirm: Callable[[str], str] = input, cfg: Optional[Config] = None, runner=None) -> int:
    cfg = cfg or Config()
    ap = argparse.ArgumentParser(prog="python -m src.cli")
    ap.add_argument("command", choices=["notes", "scope", "abstract", "downstream", "run", "smoke"])
    ap.add_argument("--condition", choices=sorted(cfg.conditions))
    ap.add_argument("--notes", help="notes folder, e.g. runs/notes_<ts>")
    ap.add_argument("--run", help="existing run folder to resume (default: a new one)")
    ap.add_argument("--live", action="store_true", help="make real model calls (default: stub backend)")
    ap.add_argument("--max-calls", type=int, default=None)
    args = ap.parse_args(argv)
    ctx: dict = {}
    try:
        return _dispatch(args, ap, cfg, confirm, runner, ctx)
    except (LLMError, StageError, ManifestError, NotImplementedError) as e:
        print("STOPPED: %s" % e, file=sys.stderr)
        return 1
    finally:
        if ctx.get("llm"):
            ctx["llm"].close()
        if ctx.get("run_dir"):
            n = record_rejected(ctx["run_dir"])
            if n:
                print("rejected calls in this run: %d (see calls/*.rejected*.json)" % n, file=sys.stderr)


def _dispatch(args, ap, cfg: Config, confirm, runner, ctx: dict) -> int:
    cmd = args.command
    _guard_live(cfg, args.live)
    if cmd in ("scope", "abstract", "downstream", "run") and not args.condition:
        ap.error("--condition is required for %s" % cmd)
    budget = CallBudget(args.max_calls)

    if cmd == "smoke":
        return _smoke(cfg, args, budget, confirm, runner, ctx)

    if cmd == "notes":
        run_dir, run_id, _ = _open_run(cfg, args, "notes", None, None)
        ctx["run_dir"] = run_dir
        ids = stages.planned_calls(cfg, "notes", None)
        preflight([("notes", len(ids), _pending(run_dir, ids))], args.live, args.max_calls, confirm)
        llm = ctx["llm"] = LLM(cfg, run_dir, run_id, "none", args.live, budget, runner)
        stages.notes_stage(cfg, llm, run_dir)
        print("notes written to %s" % run_dir)
        return 0

    cond = args.condition
    run_stages = ["scope", "abstract", "downstream"] if cmd == "run" else [cmd]
    memory = stages.has_memory(cfg, cond)
    notes_dir = Path(args.notes) if args.notes and memory else None
    if args.run and memory and not notes_dir:
        notes_dir = Path(read_json(Path(args.run) / "manifest.json")["notes_dir"])
    if memory and not notes_dir:
        ap.error("--notes is required when starting a new run")
    run_dir, run_id, _ = _open_run(cfg, args, "condition", cond, notes_dir)
    ctx["run_dir"] = run_dir
    plan = []
    for s in run_stages:
        ids = stages.planned_calls(cfg, s, cond)
        plan.append((s, len(ids), _pending(run_dir, ids)))
    preflight(plan, args.live, args.max_calls, confirm)
    llm = ctx["llm"] = LLM(cfg, run_dir, run_id, cond, args.live, budget, runner)
    notes_rows = stages.load_notes(cfg, notes_dir) if memory else []
    gated = cfg.condition(cond)["gates"]
    for s in run_stages:
        if s == "scope":
            if not memory:
                stages.empty_stage(cfg, run_dir)
            elif gated:
                stages.scope_stage(cfg, llm, run_dir, cond, notes_rows)
            else:
                stages.baseline_stage(cfg, run_dir, cond, notes_rows)
        elif s == "abstract" and gated:
            stages.abstract_stage(cfg, llm, run_dir, cond, notes_rows)
        elif s == "downstream":
            if not memory:
                stages.empty_stage(cfg, run_dir)
            stages.downstream_stage(cfg, llm, run_dir, cond)
    print("done: %s" % run_dir)
    return 0


SMOKE_IDS = ["smoke_L0", "smoke_L1", "smoke_L2", "smoke_L2_stateful", "smoke_L2_resume"]


def _smoke(cfg: Config, args, budget, confirm, runner, ctx: dict) -> int:
    run_dir, run_id, _ = _open_run(cfg, args, "smoke", None, None)
    ctx["run_dir"] = run_dir
    preflight([("smoke", len(SMOKE_IDS), _pending(run_dir, SMOKE_IDS))], args.live, args.max_calls, confirm)
    llm = ctx["llm"] = LLM(cfg, run_dir, run_id, "smoke", args.live, budget, runner)
    print("%-18s %8s %10s %10s %8s %9s" % ("call", "input", "cache_wr", "cache_rd", "output", "cost_usd"))

    def show(call_id, r):
        u = r.usage
        print("%-18s %8s %10s %10s %8s %9s" % (call_id, u["input_tokens"], u["cache_write_tokens"],
                                              u["cache_read_tokens"], u["output_tokens"], u["total_cost_usd"]))
        print("  reply: %s" % r.text.strip().replace("\n", "\n         "))

    for level in ("L0", "L1", "L2"):
        cid = "smoke_" + level
        show(cid, llm.call("downstream", "smoke", cid, SMOKE_PROMPT, overhead=level))
    first = llm.call("downstream", "smoke", "smoke_L2_stateful", SMOKE_PROMPT, overhead="L2", stateful=True)
    show("smoke_L2_stateful", first)
    show("smoke_L2_resume", llm.call("downstream", "smoke", "smoke_L2_resume", SMOKE_RESUME_PROMPT,
                                     session_id=first.session_id, stateful=True, overhead="L2"))
    print("usage: %s/usage.jsonl" % run_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
