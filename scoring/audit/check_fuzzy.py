#!/usr/bin/env python3
"""Near-duplicate paragraphs across different matters in ../firm."""
import json
import re
import sys
from difflib import SequenceMatcher
from itertools import combinations
from pathlib import Path

HERE = Path(__file__).resolve().parent
FIRM = HERE.parent.parent / "firm"
REVIEW = HERE.parent / "review" / "seed_added_lines.txt"
REGISTRY = HERE.parent / "registry.jsonl"
THRESHOLD = 0.75
MIN_WORDS = 8

BOILERPLATE = re.compile(
    r"(?i)(\bcase no\b|\bcivil action\b|\bin the .{0,40}\bcourt\b|\bdistrict of\b|\bplaintiffs?\b.{0,20}\bv\.|"
    r"\brespectfully\b|\bsincerely\b|\bbest regards\b|\besq\b|\bbar no\b|\bcertificate of service\b|"
    r"\blacks knowledge or information\b|\breserves? the right\b|\bprivileged (and|&) confidential\b|"
    r"\battorney[- ]client\b|\bwork product\b|\bdenies each and every\b|\bfails? to state a claim\b|"
    r"\bwithout waiver\b|\bplease (let me know|call|contact)\b|\bthank you\b|^\s*\*{0,2}(from|to|cc|date|subject|re):)"
)


def paragraphs():
    out = []
    for p in sorted(FIRM.rglob("*")):
        rel = p.relative_to(FIRM).parts
        if not p.is_file() or ".git" in rel or len(rel) < 3:
            continue
        raw = p.read_bytes()
        if b"\x00" in raw:
            continue
        lines = raw.decode("utf-8", errors="replace").splitlines()
        buf, start = [], None
        for i, line in enumerate(lines + [""], 1):
            if line.strip():
                if start is None:
                    start = i
                buf.append(line.strip())
            elif buf:
                text = " ".join(buf)
                if len(text.split()) >= MIN_WORDS:
                    out.append((rel[1], p, start, text))
                buf, start = [], None
    return out


def norm(t):
    return " ".join(t.split()).lower()


def load_seeds():
    return [norm(l[1:]) for l in REVIEW.read_text(encoding="utf-8").splitlines() if l.startswith("+") and l[1:].strip()]


def load_registry():
    rows = [json.loads(l) for l in REGISTRY.read_text(encoding="utf-8").splitlines() if l.strip()]
    pats = []
    for r in rows:
        for term in [r["text"]] + list(r["detection_keys"]):
            pats.append((r["id"], term, re.compile(r"(?<!\w)" + re.escape(term) + r"(?!\w)", re.IGNORECASE)))
    return rows, pats


def classify(text, seeds, pats):
    """Return (is_seed_line, [(registry id, term)]) for a paragraph."""
    n = norm(text)
    is_seed = any(s in n or n in s for s in seeds)
    ids = []
    for rid, term, rx in pats:
        if rx.search(text) and (rid, term) not in ids:
            ids.append((rid, term))
    return is_seed, ids


def main():
    paras = paragraphs()
    hits = []
    for (ma, pa, la, ta), (mb, pb, lb, tb) in combinations(paras, 2):
        if ma == mb:
            continue
        sm = SequenceMatcher(None, ta, tb, autojunk=False)
        if sm.real_quick_ratio() < THRESHOLD or sm.quick_ratio() < THRESHOLD:
            continue
        r = sm.ratio()
        if r >= THRESHOLD:
            bp = bool(BOILERPLATE.search(ta) and BOILERPLATE.search(tb))
            hits.append((r, bp, pa, la, ma, ta, pb, lb, mb, tb))
    hits.sort(key=lambda h: -h[0])

    print(f"Paragraphs compared (>= {MIN_WORDS} words): {len(paras)}; threshold {THRESHOLD}")
    for r, bp, pa, la, ma, ta, pb, lb, mb, tb in hits:
        print(f"\n  ratio {r:.3f}{'  [likely boilerplate]' if bp else ''}")
        print(f"    {pa}:{la} ({ma}): {ta[:140]}")
        print(f"    {pb}:{lb} ({mb}): {tb[:140]}")
    n_bp = sum(h[1] for h in hits)
    seeds = load_seeds()
    _, pats = load_registry()
    print(f"\n--- Section 2: seeded-paragraph involvement ({len(seeds)} seed lines; registry text and detection keys matched case-insensitively on word boundaries) ---")
    involved = 0
    for r, bp, pa, la, ma, ta, pb, lb, mb, tb in hits:
        ca, cb = classify(ta, seeds, pats), classify(tb, seeds, pats)
        scope = "same-client" if ma.split("-")[0] == mb.split("-")[0] else "cross-client"
        inv = ca[0] or cb[0] or ca[1] or cb[1]
        involved += bool(inv)
        print(f"\n  ratio {r:.3f}  {scope}  ({ma} / {mb})")
        for tag, p, l, c in (("A", pa, la, ca), ("B", pb, lb, cb)):
            print(f"    {tag} {p.relative_to(FIRM)}:{l}: seed line: {'yes' if c[0] else 'no'}; registry/key matches: " + (", ".join(f"{i}:{t!r}" for i, t in c[1]) or "none"))
    print(f"\npairs involving a seeded paragraph: {involved}")
    print(f"\n{len(hits)} pair(s) at or above {THRESHOLD}; {n_bp} flagged likely boilerplate (still counted)")
    print("FAIL" if hits else "PASS")
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main())
