"""Small file helpers for run folders. Writes are atomic; run folders are never reused by accident."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List


def stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_run_dir(runs_root: Path, run_id: str) -> Path:
    d = Path(runs_root) / run_id
    d.mkdir(parents=True, exist_ok=False)
    return d


def write_text(path: Path, text: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(str(tmp), str(path))


def write_json(path: Path, obj) -> None:
    write_text(path, json.dumps(obj, indent=2, ensure_ascii=False) + "\n")


def read_json(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def append_jsonl(path: Path, row: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def read_jsonl(path: Path) -> List[dict]:
    path = Path(path)
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def write_jsonl(path: Path, rows: Iterable[dict]) -> None:
    write_text(path, "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
