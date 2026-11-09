"""The four stages. Each reads the previous stage's files from disk and checkpoints after every call."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, List, Optional

from .config import Config, sha256_text
from .llm import LLM
from .runfs import iso_now, read_json, read_jsonl, write_json, write_jsonl, write_text
from .stores import (StageError, exclude_walled, load_store, rebuild_baseline, rebuild_gated,
                     render_items, store_path, write_empty_stores, validate_tags, verify_patterns)

NOTE_TYPES = ("fact", "position", "lesson")
DECISIONS = ("client_store", "matter_only", "discard")


def extract_json(text: str):
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
    try:
        return json.loads(t)
    except ValueError:
        a, b = t.find("{"), t.rfind("}")
        if a >= 0 and b > a:
            try:
                return json.loads(t[a:b + 1])
            except ValueError:
                pass
    raise StageError("model output is not valid JSON: %.300s" % text)


def artifact_id(matter: str) -> str:
    return "N" + sha256_text("artifact:" + matter)[:6]


def rejecting(llm: LLM, call_id: str, fn, *args):
    """Run a validator on a call's output; on rejection set the call aside, then stop."""
    try:
        return fn(*args)
    except StageError as e:
        llm.reject(call_id, str(e))
        raise StageError("%s Call %s set aside as calls/%s.rejected*.json; rerun to retry it."
                         % (e, call_id, call_id))


# ---------- planned calls (for the preflight) ----------

def load_probes(cfg: Config) -> List[dict]:
    probes = read_jsonl(cfg.probes_path)
    for p in probes:
        if p["new_matter"] not in cfg.new_matters:
            raise StageError("probe %s names unknown matter %s" % (p["id"], p["new_matter"]))
    return probes


def has_memory(cfg: Config, condition: Optional[str]) -> bool:
    return bool(cfg.condition(condition).get("memory", True)) if condition else True


def planned_calls(cfg: Config, stage: str, condition: Optional[str]) -> List[str]:
    if stage == "notes":
        return ["notes_" + m for m in cfg.source_matters]
    if stage in ("scope", "abstract") and not has_memory(cfg, condition):
        return []
    gated = cfg.condition(condition)["gates"]
    if stage == "scope":
        return ["scope_" + m for m in cfg.source_matters] if gated else []
    if stage == "abstract":
        return ["abstraction"] if gated else []
    if stage == "downstream":
        return ["down_" + p["id"] for p in load_probes(cfg)]
    raise ValueError(stage)


# ---------- stage 1: notes ----------

def documents_text(cfg: Config, matter: str) -> str:
    d = cfg.firm_dir / cfg.client_letter(matter) / matter
    files = sorted(d.glob("*.md"))
    if not files:
        raise StageError("no documents found in %s" % d)
    return "\n\n".join("=== %s ===\n%s" % (f.name, f.read_text(encoding="utf-8").strip()) for f in files)


def _parse_notes(text: str, matter: str, aid: str) -> List[dict]:
    obj = extract_json(text)
    items = obj.get("items") if isinstance(obj, dict) else None
    if not items:
        raise StageError("notes for %s: no items in model output" % matter)
    out = []
    for n, it in enumerate(items, 1):
        if not isinstance(it, dict) or it.get("type") not in NOTE_TYPES or \
                not isinstance(it.get("text"), str) or not it["text"].strip():
            raise StageError("notes for %s: bad item %r" % (matter, it))
        out.append({"id": "%s.%02d" % (aid, n), "type": it["type"], "text": it["text"].strip()})
    return out


def notes_stage(cfg: Config, llm: LLM, notes_dir: Path) -> None:
    for matter in cfg.source_matters:
        prompt = cfg.prompt("notes").substitute(
            matter=matter, client=cfg.client_name(matter), documents=documents_text(cfg, matter))
        res = llm.call("notes", "notes", "notes_" + matter, prompt)
        aid = artifact_id(matter)
        out = rejecting(llm, "notes_" + matter, _parse_notes, res.text, matter, aid)
        write_json(Path(notes_dir) / "notes" / (matter + ".json"),
                   {"matter": matter, "client": cfg.client_name(matter), "artifact_id": aid,
                    "call_id": "notes_" + matter, "timestamp": res.timestamp, "items": out})
        write_text(Path(notes_dir) / "notes" / (matter + ".md"),
                   "# Notes: %s (%s)\n\n" % (matter, cfg.client_name(matter)) +
                   "\n".join("%s. [%s] %s" % (i["id"], i["type"], i["text"]) for i in out) + "\n")
        _write_notes_index(cfg, notes_dir)


def _write_notes_index(cfg: Config, notes_dir: Path) -> None:
    rows = []
    for m in cfg.source_matters:
        f = Path(notes_dir) / "notes" / (m + ".json")
        if f.exists():
            g = read_json(f)
            for it in g["items"]:
                rows.append({"artifact_id": g["artifact_id"], "matter": m, "client": g["client"], **it})
    write_jsonl(Path(notes_dir) / "notes.jsonl", rows)


def load_notes(cfg: Config, notes_dir: Path) -> List[dict]:
    rows = read_jsonl(Path(notes_dir) / "notes.jsonl")
    have = {r["matter"] for r in rows}
    missing = [m for m in cfg.source_matters if m not in have]
    if missing:
        raise StageError("notes in %s are incomplete (missing %s). Run the notes stage first." % (notes_dir, missing))
    return rows


# ---------- stage 2: scope gate ----------

def validate_scope(text: str, expected_ids: List[str], cfg: Config) -> dict:
    obj = extract_json(text)
    items = obj.get("items") if isinstance(obj, dict) else None
    if not isinstance(items, list):
        raise StageError("scope gate: output has no 'items' list")
    out, seen = [], set()
    for it in items:
        if not isinstance(it, dict):
            raise StageError("scope gate: entry is not an object: %r" % (it,))
        i = it.get("id")
        if i not in expected_ids or i in seen:
            raise StageError("scope gate: unknown or repeated item id %r" % i)
        seen.add(i)
        if it.get("decision") not in DECISIONS:
            raise StageError("scope gate: bad decision %r for %s" % (it.get("decision"), i))
        row = {"id": i, "decision": it["decision"], "tags": validate_tags(it.get("tags"), cfg)}
        if it.get("text"):
            if not isinstance(it["text"], str):
                raise StageError("scope gate: text of %s is not a string" % i)
            row["text"] = it["text"].strip()
        out.append(row)
    missing = [i for i in expected_ids if i not in seen]
    if missing:
        raise StageError("scope gate: no decision for items %s" % missing)
    return {"items": out}


def _last_scope_session(run_dir: Path, cfg: Config) -> Optional[str]:
    f = Path(run_dir) / "gate_raw" / ("scope_%s.json" % cfg.source_matters[-1])
    return read_json(f)["session_id"] if f.exists() else None


def empty_stage(cfg: Config, run_dir: Path) -> None:
    write_empty_stores(run_dir, cfg)


def baseline_stage(cfg: Config, run_dir: Path, condition: str, notes_rows: List[dict]) -> None:
    rebuild_baseline(run_dir, cfg, condition, notes_rows, iso_now())


def scope_stage(cfg: Config, llm: LLM, run_dir: Path, condition: str, notes_rows: List[dict]) -> None:
    stateful = cfg.condition(condition)["stateful"]
    session = None
    for matter in cfg.source_matters:
        items = [n for n in notes_rows if n["matter"] == matter]
        prompt = cfg.prompt("scope_gate").substitute(
            walls=cfg.walls_text(), matter=matter, client=cfg.client_name(matter),
            items="\n".join("- [%s] (%s) %s" % (n["id"], n["type"], n["text"]) for n in items))
        res = llm.call("scope_gate", "scope_gate", "scope_" + matter, prompt,
                       session_id=session if stateful else None, stateful=stateful)
        if stateful:
            session = res.session_id
        parsed = rejecting(llm, "scope_" + matter, validate_scope, res.text, [n["id"] for n in items], cfg)
        write_json(Path(run_dir) / "gate_raw" / ("scope_%s.json" % matter),
                   {"matter": matter, "call_id": "scope_" + matter, "timestamp": res.timestamp,
                    "session_id": res.session_id, "raw": res.text, "parsed": parsed})
        rebuild_gated(run_dir, cfg, condition, notes_rows)


# ---------- stage 3: abstraction gate ----------

def validate_patterns(text: str, cfg: Config) -> List[dict]:
    obj = extract_json(text)
    pats = obj.get("patterns") if isinstance(obj, dict) else None
    if not isinstance(pats, list):
        raise StageError("abstraction gate: output has no 'patterns' list")
    out = []
    for p in pats:
        if not isinstance(p, dict):
            raise StageError("abstraction gate: entry is not an object: %r" % (p,))
        if not isinstance(p.get("text"), str) or not p["text"].strip() or \
                not isinstance(p.get("contributing_items"), list):
            raise StageError("abstraction gate: bad pattern %r" % (p,))
        out.append({"text": p["text"].strip(), "contributing_items": [str(i) for i in p["contributing_items"]],
                    "tags": validate_tags(p.get("tags"), cfg)})
    return out


def abstract_stage(cfg: Config, llm: LLM, run_dir: Path, condition: str, notes_rows: List[dict]) -> None:
    stateful = cfg.condition(condition)["stateful"]
    for m in cfg.source_matters:
        if not (Path(run_dir) / "gate_raw" / ("scope_%s.json" % m)).exists():
            raise StageError("scope gate has not finished (missing %s). Run the scope stage first." % m)
    rebuild_gated(run_dir, cfg, condition, notes_rows)
    blocks, item_client = [], {}
    for letter, name in cfg.clients.items():
        rows = load_store(store_path(run_dir, "client_" + letter))
        lines = []
        for r in rows:
            item_client[r["artifact_id"]] = name
            tags = " (tags: %s)" % ", ".join(r["eligibility_tags"]) if r["eligibility_tags"] else ""
            lines.append("- [%s]%s %s" % (r["artifact_id"], tags, r["text"]))
        blocks.append("### %s\n%s" % (name, "\n".join(lines) if lines else "(empty)"))
    prompt = cfg.prompt("abstraction_gate").substitute(k=cfg.k, walls=cfg.walls_text(), stores="\n\n".join(blocks))
    session = _last_scope_session(run_dir, cfg) if stateful else None
    res = llm.call("abstraction_gate", "abstraction_gate", "abstraction", prompt,
                   session_id=session, stateful=stateful)
    kept, dropped = verify_patterns(rejecting(llm, "abstraction", validate_patterns, res.text, cfg), item_client, cfg.k)
    write_json(Path(run_dir) / "gate_raw" / "abstraction.json",
               {"call_id": "abstraction", "timestamp": res.timestamp, "session_id": res.session_id,
                "raw": res.text, "kept": kept, "dropped": dropped})
    rebuild_gated(run_dir, cfg, condition, notes_rows)


# ---------- stage 4: downstream ----------

def downstream_stage(cfg: Config, llm: LLM, run_dir: Path, condition: str) -> None:
    firm = load_store(store_path(run_dir, "firm"))
    done = []
    for p in load_probes(cfg):
        matter, letter = p["new_matter"], cfg.client_letter(p["new_matter"])
        client = exclude_walled(load_store(store_path(run_dir, "client_" + letter)), matter)
        prompt = cfg.prompt("downstream").substitute(
            client=cfg.client_name(matter), matter=matter, probe=p["text"],
            client_store=render_items(client), firm_store=render_items(exclude_walled(firm, matter)))
        res = llm.call("downstream", "downstream", "down_" + p["id"], prompt)
        done.append({"run_id": llm.run_id, "condition": condition, "probe_id": p["id"],
                     "new_matter": matter, "text": res.text, "call_id": "down_" + p["id"],
                     "timestamp": res.timestamp})
        write_jsonl(Path(run_dir) / "probe_outputs.jsonl", done)
