"""Run manifests, git/firm-tag checks and environment versions."""
from __future__ import annotations

import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

from .config import Config, sha256_bytes
from .stores import EMPTY_STORE_MARKER
from .runfs import iso_now, read_json, write_json


class ManifestError(Exception):
    pass


def _git(root: Path, *args) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(root)] + list(args), capture_output=True, text=True)


def git_info(root: Path) -> dict:
    head = _git(root, "rev-parse", "HEAD")
    commit = head.stdout.strip() if head.returncode == 0 else None
    # runs/ is versioned run output, so it does not count as a dirty tree.
    st = _git(root, "status", "--porcelain", "--", ".", ":(exclude)runs")
    return {"commit": commit, "dirty": bool(st.stdout.strip()) if st.returncode == 0 else None}


def require_clean_git(root: Path) -> None:
    g = git_info(root)
    if g["commit"] is None:
        raise ManifestError("--live needs at least one git commit in this repository. Commit first.")
    if g["dirty"]:
        raise ManifestError("--live needs a clean working tree (runs/ is ignored by this check). "
                            "Commit or stash your changes first.")


def firm_tag_info(cfg: Config, required: bool) -> dict:
    p = cfg.firm_tag_path
    if not p.exists():
        if required:
            raise ManifestError("data/FIRM_TAG is missing. Write the firm tag name and firm commit hash there.")
        return {"tag": None, "commit": None}
    lines = [l.strip() for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
    kv = {}
    for l in lines:
        if ":" in l:
            k, v = l.split(":", 1)
            kv[k.strip().lower()] = v.strip()
    if "tag" in kv and "commit" in kv:
        info = {"tag": kv["tag"], "commit": kv["commit"]}
    else:
        toks = " ".join(lines).split()
        info = {"tag": toks[0] if toks else None, "commit": toks[1] if len(toks) > 1 else None}
    if required and not (info["tag"] and info["commit"]):
        raise ManifestError("data/FIRM_TAG must hold a tag name and a commit hash "
                            "(either two lines, or 'tag: ...' and 'commit: ...').")
    return info


def _pkg_version(name: str) -> Optional[str]:
    try:
        from importlib import metadata
        return metadata.version(name)
    except Exception:
        return None


def claude_version() -> Optional[str]:
    if not shutil.which("claude"):
        return None
    try:
        r = subprocess.run(["claude", "--version"], capture_output=True, text=True, timeout=30)
        return r.stdout.strip() or None
    except Exception:
        return None


def env_versions() -> dict:
    return {
        "python": sys.version.split()[0],
        "pyyaml": _pkg_version("PyYAML"),
        "pytest": _pkg_version("pytest"),
        "macos": platform.mac_ver()[0] or None,
        "platform": platform.platform(),
    }


def build_manifest(cfg: Config, run_id: str, kind: str, condition: Optional[str], live: bool,
                   notes_dir: Optional[str] = None, extra: Optional[dict] = None) -> dict:
    roles = cfg.pipeline["roles"]
    m = {
        "run_id": run_id,
        "kind": kind,
        "condition": condition,
        "created": iso_now(),
        "live": live,
        "config_hash": cfg.config_hash(),
        "prompts_hash": cfg.prompts_hash(),
        "downstream_prompt_hash": sha256_bytes((cfg.root / "prompts" / "downstream.md").read_bytes()),
        "empty_store_substitution": EMPTY_STORE_MARKER,
        "pipeline_git": git_info(cfg.root),
        "firm": dict(firm_tag_info(cfg, required=False), data_hash=cfg.firm_hash()),
        "probes_hash": cfg.probes_hash(),
        "backend": cfg.pipeline["backend"],
        "roles": roles,
        "models": sorted({r["model"] for r in roles.values()}),
        "temperature": cfg.pipeline["temperature"],
        "temperature_note": "claude -p exposes no temperature setting; the CLI default applies.",
        "effort": "default",
        "claude_overhead_level": cfg.pipeline.get("claude_cli", {}).get("overhead"),
        "claude_version": claude_version(),
        "versions": env_versions(),
        "notes_dir": notes_dir,
        "k": cfg.k,
        "rejected_calls": 0,
    }
    if condition:
        m["memory"] = bool(cfg.condition(condition).get("memory", True))
        note = cfg.condition(condition).get("note")
        if note:
            m["condition_note"] = " ".join(str(note).split())
    if extra:
        m.update(extra)
    return m


def write_manifest(run_dir: Path, manifest: dict) -> None:
    write_json(Path(run_dir) / "manifest.json", manifest)


def check_resume(run_dir: Path, cfg: Config) -> dict:
    mp = Path(run_dir) / "manifest.json"
    if not mp.exists():
        raise ManifestError("%s has no manifest.json; not a run folder." % run_dir)
    m = read_json(mp)
    now = {"config_hash": cfg.config_hash(), "prompts_hash": cfg.prompts_hash(),
           "probes_hash": cfg.probes_hash()}
    for k, v in now.items():
        if m.get(k) != v:
            raise ManifestError("Cannot resume %s: %s differs from the manifest. Start a new run." % (run_dir, k))
    if m["firm"]["data_hash"] != cfg.firm_hash():
        raise ManifestError("Cannot resume %s: data/firm changed since the run started." % run_dir)
    return m


def rejected_count(run_dir: Path) -> int:
    return len(list((Path(run_dir) / "calls").glob("*.rejected*.json")))


def record_rejected(run_dir: Path) -> int:
    """Write the current count of rejected calls into the run's manifest."""
    mp = Path(run_dir) / "manifest.json"
    n = rejected_count(run_dir)
    if mp.exists():
        m = read_json(mp)
        if m.get("rejected_calls") != n:
            m["rejected_calls"] = n
            write_json(mp, m)
    return n
