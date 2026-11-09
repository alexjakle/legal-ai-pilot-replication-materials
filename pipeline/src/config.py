"""Config loading, prompt loading and content hashes."""
from __future__ import annotations

import hashlib
from pathlib import Path
from string import Template
from typing import Dict, List, Optional

import yaml

ROOT = Path(__file__).resolve().parent.parent


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def hash_files(paths: List[Path], base: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(paths):
        h.update(str(p.relative_to(base)).encode("utf-8") + b"\0")
        h.update(p.read_bytes() + b"\0")
    return h.hexdigest()


def hash_tree(path: Path) -> str:
    return hash_files([p for p in path.rglob("*") if p.is_file()], path)


def _yaml(path: Path):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


class Config:
    def __init__(self, root: Path = ROOT, runs_root: Optional[Path] = None):
        self.root = Path(root)
        self.pipeline = _yaml(self.root / "config" / "pipeline.yaml")
        self.conditions = _yaml(self.root / "config" / "conditions.yaml")
        self.walls = _yaml(self.root / "config" / "walls.yaml")["walls"]
        p = self.pipeline
        self.runs_root = Path(runs_root) if runs_root else self.root / p["runs_dir"]
        self.firm_dir = self.root / p["firm_dir"]
        self.probes_path = self.root / p["probes_path"]
        self.firm_tag_path = self.root / p["firm_tag_path"]
        self.clients: Dict[str, str] = p["clients"]
        self.matters: Dict[str, str] = p["matters"]
        self.source_matters: List[str] = p["source_matters"]
        self.new_matters: List[str] = p["new_matters"]
        self.k: int = p["k"]

    def client_letter(self, matter: str) -> str:
        return self.matters[matter]

    def client_name(self, matter: str) -> str:
        return self.clients[self.matters[matter]]

    def letter_for_name(self, name: str) -> str:
        for letter, n in self.clients.items():
            if n == name:
                return letter
        raise KeyError(name)

    def role(self, role: str) -> dict:
        try:
            return self.pipeline["roles"][role]
        except KeyError:
            raise KeyError("no such role in config/pipeline.yaml: %s" % role)

    def condition(self, name: str) -> dict:
        try:
            return self.conditions[name]
        except KeyError:
            raise KeyError("unknown condition %s; see config/conditions.yaml" % name)

    def prompt(self, name: str) -> Template:
        return Template((self.root / "prompts" / (name + ".md")).read_text(encoding="utf-8"))

    def walls_text(self) -> str:
        lines = []
        for w in self.walls:
            lines.append(
                "- Material from matter %s must not be visible to matter %s."
                % (w["hidden"], ", ".join(w["from"]))
            )
        return "\n".join(lines) if lines else "(none)"

    def config_hash(self) -> str:
        d = self.root / "config"
        return hash_files([p for p in d.glob("*.yaml")], d)

    def prompts_hash(self) -> str:
        d = self.root / "prompts"
        return hash_files([p for p in d.glob("*.md")], d)

    def firm_hash(self) -> str:
        return hash_tree(self.firm_dir)

    def probes_hash(self) -> str:
        return sha256_bytes(self.probes_path.read_bytes())
