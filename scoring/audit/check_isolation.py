#!/usr/bin/env python3
"""(a) pipeline must not reference scoring; (b) firm must not leak the answer key; (c) firm layout."""
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCORING = HERE.parent
ROOT = SCORING.parent
PIPELINE = ROOT / "pipeline"
FIRM = ROOT / "firm"
REGISTRY = SCORING / "registry.jsonl"

PIPE_TERMS = re.compile(r"scoring|registry|answer key", re.IGNORECASE)
FIRM_WORDS = re.compile(r"\b(?:canary|registry|planted|seed\w*|answer key)\b", re.IGNORECASE)
PATHLIKE = re.compile(r"[\w.~$@+-]*(?:/[\w.~$@+-]*)+|\.\.")

DOCS = ["01-answer.md", "02-emails.md", "03-memo.md", "04-instruction-letter.md"]
MATTERS = ["A/A-1", "A/A-2", "B/B-1", "C/C-1"]
EXPECTED = {f"{m}/{d}" for m in MATTERS for d in DOCS}


SKIP_DIRS = {".venv", "__pycache__", ".pytest_cache"}  # installed packages and caches, not pipeline code


def walk(base):
    for dp, dn, fn in os.walk(base):
        dn[:] = [d for d in dn if d not in SKIP_DIRS]
        for n in sorted(fn) + sorted(dn):
            p = Path(dp) / n
            if p.is_symlink() or p.is_file():
                yield p


def read_text(p):
    try:
        raw = p.read_bytes()
    except OSError:
        return None
    return None if b"\x00" in raw else raw.decode("utf-8", errors="replace")


def into_scoring(path):
    try:
        path.resolve().relative_to(SCORING)
        return True
    except ValueError:
        return False


def check_pipeline():
    findings, skipped, nfiles = [], [], 0
    if not PIPELINE.exists():
        return ["../pipeline does not exist"], skipped, 0, True
    for p in walk(PIPELINE):
        nfiles += 1
        if p.is_symlink() and into_scoring(p):
            findings.append(f"{p}: symlink resolves into scoring ({p.resolve()})")
        if p.is_symlink() and not p.is_file():
            continue
        t = read_text(p)
        if t is None:
            skipped.append(p)
            continue
        for i, line in enumerate(t.splitlines(), 1):
            for m in PIPE_TERMS.finditer(line):
                findings.append(f"{p}:{i}: term {m.group(0)!r}: {line.strip()[:120]}")
            for tok in PATHLIKE.findall(line):
                try:
                    cands = [Path(tok).expanduser()]
                except RuntimeError:  # a token like '~+-' is not a home path
                    cands = [p.parent / tok, PIPELINE / tok]
                if not Path(tok).is_absolute():
                    cands = [p.parent / tok, PIPELINE / tok]
                if any(into_scoring(c) for c in cands) and not PIPE_TERMS.search(tok):
                    findings.append(f"{p}:{i}: path resolves into scoring: {tok}")
    non_git = [p for p in walk(PIPELINE) if ".git" not in p.relative_to(PIPELINE).parts]
    return findings, skipped, nfiles, not non_git


def git_tracked():
    out = subprocess.run(["git", "-C", str(FIRM), "ls-files", "-z"], capture_output=True, check=True).stdout
    return sorted(x for x in out.decode("utf-8").split("\0") if x)


def build_matchers():
    ids = [json.loads(l)["id"] for l in REGISTRY.read_text(encoding="utf-8").splitlines() if l.strip()]
    ids = sorted(set(ids) | {f"F{n:02d}" for n in range(1, 17)})
    id_re = re.compile(r"(?<![A-Za-z0-9-])(" + "|".join(re.escape(i) for i in ids) + r")(?![A-Za-z0-9-])", re.IGNORECASE)
    return id_re, len(ids)


def scan_files(paths, id_re, label=lambda p: p):
    findings, skipped = [], []
    for p in paths:
        t = read_text(p)
        if t is None:
            skipped.append(p)
            continue
        for i, line in enumerate(t.splitlines(), 1):
            for m in id_re.finditer(line):
                findings.append(f"{label(p)}:{i}: registry id {m.group(0)!r}: {line.strip()[:120]}")
            for m in FIRM_WORDS.finditer(line):
                findings.append(f"{label(p)}:{i}: word {m.group(0)!r}: {line.strip()[:120]}")
    return findings, skipped


def check_firm_content():
    id_re, n_ids = build_matchers()
    tracked = git_tracked()
    findings, skipped = scan_files([FIRM / t for t in tracked], id_re)
    log_files = [p for p in walk(FIRM / ".git" / "logs")] if (FIRM / ".git" / "logs").exists() else []
    known, _ = scan_files(log_files, id_re)
    return findings, skipped, n_ids, len(tracked), known


def check_export():
    """Clean export via git archive HEAD into a fresh temp dir; scan it; delete it."""
    id_re, _ = build_matchers()
    tmp = Path(tempfile.mkdtemp(prefix="firm_export_"))
    findings, n = [], 0
    try:
        proc = subprocess.run(["git", "-C", str(FIRM), "archive", "HEAD"], capture_output=True)
        if proc.returncode != 0:
            return [f"git archive failed: {proc.stderr.decode()[:200]}"], 0, False
        tar = tmp / "export.tar"
        tar.write_bytes(proc.stdout)
        dest = tmp / "export"
        dest.mkdir()
        with tarfile.open(tar) as tf:
            for mem in tf.getmembers():
                if mem.name.startswith(("/", "..")) or ".." in Path(mem.name).parts or not (mem.isfile() or mem.isdir()):
                    findings.append(f"export has unsafe/unexpected member: {mem.name}")
                    continue
                tf.extract(mem, dest)
        files = list(walk(dest))
        n = len(files)
        if any(".git" in p.relative_to(dest).parts for p in files) or (dest / ".git").exists():
            findings.append("export contains a .git entry")
        f, skipped = scan_files(files, id_re, label=lambda p: p.relative_to(dest))
        findings += f
        if skipped:
            findings.append(f"export has {len(skipped)} unreadable/binary file(s): {[str(x.relative_to(dest)) for x in skipped]}")
        got = {p.relative_to(dest).as_posix() for p in files}
        if got != EXPECTED:
            findings.append(f"export file set differs from the 16 expected documents: extra={sorted(got - EXPECTED)} missing={sorted(EXPECTED - got)}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return findings, n, not tmp.exists()


def check_firm_layout():
    tracked = set(git_tracked())
    extras = [f"{FIRM / t}: tracked but not an expected document" for t in sorted(tracked - EXPECTED)]
    missing = [f"{FIRM / m}: expected file missing from git" for m in sorted(EXPECTED - tracked)]
    info = []
    for p in sorted(FIRM.rglob("*")):
        rel = p.relative_to(FIRM)
        if rel.parts[0] == ".git" or p.is_dir():
            continue
        if rel.as_posix() not in tracked:
            info.append(f"{p}: on disk, untracked")
    return extras + missing, info, (FIRM / ".git").exists()


def section(title, findings):
    print(f"\n{title}: {len(findings)} finding(s)")
    for f in findings:
        print(f"  {f}")


def main():
    a, a_skipped, a_n, a_empty = check_pipeline()
    b, b_skipped, n_ids, n_tracked, known = check_firm_content()
    b2, n_exp, deleted = check_export()
    c, c_info, has_git = check_firm_layout()

    print(f"(a) ../pipeline: {a_n} entries scanned (including .git, binary files skipped: {len(a_skipped)})")
    if a_empty:
        print("  ../pipeline contains nothing but .git (or is empty); (a) passes")
        a = [f for f in a if "does not exist" in f]
    section("(a) pipeline references to scoring", a)
    print(f"\n(b) ../firm: {n_tracked} git-tracked files (working-tree contents); checked {n_ids} registry ids and words {FIRM_WORDS.pattern!r}")
    print(f"  binary files skipped: {len(b_skipped)}")
    section("(b) answer-key leakage in tracked firm files", b)
    print(f"\nKNOWN EXPOSURE: firm/.git history (informational, not FAIL): {len(known)} match(es) in ../firm/.git/logs")
    for f in known:
        print(f"  {f}")
    print(f"\n(b2) clean export (git archive HEAD): {n_exp} files; temp dir deleted: {deleted}")
    section("(b2) export checks (no .git, no terms/ids, expected file set)", b2)
    print(f"\n(c) ../firm/.git present: {has_git}")
    section("(c) firm layout (git-tracked vs 16 expected)", c)
    print(f"\n(c) INFO on-disk untracked files (not counted): {len(c_info)}")
    for f in c_info:
        print(f"  {f}")

    bad = len(a) + len(b) + len(b2) + len(c)
    print("\nFAIL" if bad else "\nPASS", f"- {bad} finding(s)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
