"""Stores: loading, wall exclusion, rendering, and rebuilding from gate outputs.

Store rows carry artifact metadata only (artifact_id, store, client,
eligibility_tags, creating_stage) plus type and text. They never carry a source
matter; that lives only in ledger.jsonl.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .config import Config
from .runfs import read_json, read_jsonl, write_jsonl, write_text

_TAG = re.compile(r"^wall:(.+)$")


EMPTY_STORE_MARKER = "(empty)"


class StageError(Exception):
    pass


def store_path(run_dir: Path, name: str, ext: str = "jsonl") -> Path:
    return Path(run_dir) / "stores" / ("%s.%s" % (name, ext))


def load_store(path: Path) -> List[dict]:
    return read_jsonl(path)


def exclude_walled(rows: List[dict], matter: str) -> List[dict]:
    tag = "wall:%s" % matter
    return [r for r in rows if tag not in (r.get("eligibility_tags") or [])]


def render_items(rows: List[dict]) -> str:
    return "\n".join("- " + r["text"] for r in rows) if rows else EMPTY_STORE_MARKER


def validate_tags(tags, cfg: Config) -> List[str]:
    if tags is None:
        return []
    if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
        raise StageError("tags must be a list of strings, got %r" % (tags,))
    for t in tags:
        m = _TAG.match(t)
        if not m or m.group(1) not in cfg.matters:
            raise StageError("bad eligibility tag %r (expected wall:<known matter>)" % t)
    return tags


def verify_patterns(patterns: List[dict], item_client: Dict[str, str], k: int) -> Tuple[List[dict], List[dict]]:
    """Keep a pattern only if its contributing items span at least k distinct clients."""
    kept, dropped = [], []
    for p in patterns:
        ids = [i for i in p["contributing_items"] if i in item_client]
        clients = {item_client[i] for i in ids}
        if len(clients) >= k:
            kept.append(dict(p, contributing_items=ids))
        else:
            dropped.append(dict(p, reason="%d distinct client(s) among known contributing items, need %d"
                                % (len(clients), k)))
    return kept, dropped


def _meta(artifact_id, store, client, tags, stage, typ, text) -> dict:
    return {"artifact_id": artifact_id, "store": store, "client": client,
            "eligibility_tags": tags, "creating_stage": stage, "type": typ, "text": text}


def _md(title: str, rows: List[dict]) -> str:
    out = ["# %s" % title, ""]
    for r in rows:
        tags = " (tags: %s)" % ", ".join(r["eligibility_tags"]) if r["eligibility_tags"] else ""
        out.append("- `%s` [%s]%s %s" % (r["artifact_id"], r["type"], tags, r["text"]))
    return "\n".join(out) + "\n"


def _write_stores(run_dir: Path, cfg: Config, clients: Dict[str, List[dict]], firm: List[dict],
                  matter_only: List[dict], discarded: List[dict], ledger: List[dict]) -> None:
    for letter, name in cfg.clients.items():
        rows = clients.get(letter, [])
        write_jsonl(store_path(run_dir, "client_" + letter), rows)
        write_text(store_path(run_dir, "client_" + letter, "md"), _md("Client store: " + name, rows))
    write_jsonl(store_path(run_dir, "firm"), firm)
    write_text(store_path(run_dir, "firm", "md"), _md("Firm store", firm))
    write_jsonl(store_path(run_dir, "matter_only"), matter_only)
    write_jsonl(store_path(run_dir, "discarded"), discarded)
    write_jsonl(Path(run_dir) / "ledger.jsonl", ledger)


def write_empty_stores(run_dir: Path, cfg: Config) -> None:
    """N0: every store file exists and is empty, so downstream runs the same code path."""
    _write_stores(run_dir, cfg, {}, [], [], [], [])


def rebuild_baseline(run_dir: Path, cfg: Config, condition: str, notes_rows: List[dict], timestamp: str) -> None:
    clients: Dict[str, List[dict]] = {l: [] for l in cfg.clients}
    firm, ledger = [], []
    for n in notes_rows:
        letter = cfg.letter_for_name(n["client"])
        clients[letter].append(_meta(n["id"], "client", n["client"], [], "notes", n["type"], n["text"]))
        firm.append(_meta(n["id"], "firm", None, [], "notes", n["type"], n["text"]))
        for gate in ("baseline_client", "baseline_firm"):
            ledger.append({"artifact_id": n["id"], "source_matter": n["matter"], "gate": gate,
                           "condition": condition, "timestamp": timestamp})
    _write_stores(run_dir, cfg, clients, firm, [], [], ledger)


def rebuild_gated(run_dir: Path, cfg: Config, condition: str, notes_rows: List[dict]) -> None:
    """Replay gate_raw/ into stores and ledger. Idempotent."""
    note_by_id = {n["id"]: n for n in notes_rows}
    clients: Dict[str, List[dict]] = {l: [] for l in cfg.clients}
    matter_only, discarded, firm, ledger = [], [], [], []
    raw = Path(run_dir) / "gate_raw"
    for matter in cfg.source_matters:
        f = raw / ("scope_%s.json" % matter)
        if not f.exists():
            break
        g = read_json(f)
        for d in g["parsed"]["items"]:
            n = note_by_id[d["id"]]
            ledger.append({"artifact_id": d["id"], "source_matter": matter, "gate": "scope_gate",
                           "condition": condition, "timestamp": g["timestamp"]})
            text = d.get("text") or n["text"]
            tags = d.get("tags") or []
            if d["decision"] == "client_store":
                clients[cfg.letter_for_name(n["client"])].append(
                    _meta(d["id"], "client", n["client"], tags, "scope_gate", n["type"], text))
            elif d["decision"] == "matter_only":
                matter_only.append(_meta(d["id"], "matter_only", n["client"], tags, "scope_gate", n["type"], text))
            else:
                discarded.append(_meta(d["id"], "discard", n["client"], tags, "scope_gate", n["type"], text))
    a = raw / "abstraction.json"
    if a.exists():
        g = read_json(a)
        for i, p in enumerate(g["kept"], 1):
            fid = "firm-%02d" % i
            firm.append(_meta(fid, "firm", None, p.get("tags") or [], "abstraction_gate", "pattern", p["text"]))
            for matter in sorted({note_by_id[c]["matter"] for c in p["contributing_items"]}):
                ledger.append({"artifact_id": fid, "source_matter": matter, "gate": "abstraction_gate",
                               "condition": condition, "timestamp": g["timestamp"]})
    _write_stores(run_dir, cfg, clients, firm, matter_only, discarded, ledger)
