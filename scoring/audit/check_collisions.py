#!/usr/bin/env python3
"""Verbatim planted facts: find hits of text and detection_keys outside their own matter."""
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCORING = HERE.parent
FIRM = SCORING.parent / "firm"
REGISTRY = SCORING / "registry.jsonl"
ALLOWLIST = HERE / "allowlist.txt"


def load_allowlist():
    if not ALLOWLIST.exists():
        return set()
    return {l.strip() for l in ALLOWLIST.read_text(encoding="utf-8").splitlines() if l.strip()}


def firm_files():
    for p in sorted(FIRM.rglob("*")):
        if p.is_file() and ".git" not in p.relative_to(FIRM).parts:
            yield p


def locate(path):
    parts = path.relative_to(FIRM).parts
    if len(parts) >= 3:
        return parts[0], parts[1]
    return None, None


def pattern(s):
    return re.compile(r"\s+".join(re.escape(w) for w in s.split()), re.IGNORECASE)


def main():
    allow = load_allowlist()
    facts = [json.loads(l) for l in REGISTRY.read_text(encoding="utf-8").splitlines() if l.strip()]
    verbatim = [f for f in facts if f["type"] == "verbatim"]

    texts = {}
    skipped = []
    for p in firm_files():
        raw = p.read_bytes()
        if b"\x00" in raw:
            skipped.append(p)
            continue
        texts[p] = raw.decode("utf-8", errors="replace")

    cross_client, cross_matter, allowed_reach, own_matter = [], [], [], 0
    suggest = set()
    for f in verbatim:
        for s in dict.fromkeys([f["text"]] + list(f["detection_keys"])):
            if s in allow:
                continue
            pat = pattern(s)
            for p, t in texts.items():
                client, matter = locate(p)
                for m in pat.finditer(t):
                    line = t.count("\n", 0, m.start()) + 1
                    rec = (f["id"], s, f"{p}:{line}", client, matter, f)
                    if client != f["client"]:
                        cross_client.append(rec)
                    elif matter != f["matter"]:
                        (allowed_reach if f["intended_reach"] == "client" else cross_matter).append(rec)
                    else:
                        own_matter += 1
                    if client != f["client"] or matter != f["matter"]:
                        suggest.add(s)

    def show(title, recs):
        print(f"\n{title}: {len(recs)}")
        for fid, s, loc, client, matter, f in recs:
            print(f"  {fid} {s!r} (fact: client {f['client']}, matter {f['matter']}, reach {f['intended_reach']})")
            print(f"    hit at {loc} (client {client}, matter {matter})")

    print(f"Verbatim facts checked: {len(verbatim)}; firm files read: {len(texts)}; allowlist entries: {len(allow)}")
    for p in skipped:
        print(f"  skipped binary file: {p}")
    print(f"Hits inside the fact's own matter (ignored): {own_matter}")
    show("FINDING different client", cross_client)
    show("FINDING different matter, same client, intended_reach != client", cross_matter)
    show("INFO different matter, same client, intended_reach == client (allowed)", allowed_reach)
    if suggest:
        print("\nWould add to allowlist.txt if legitimate (not added):")
        for s in sorted(suggest):
            print(f"  {s}")
    bad = len(cross_client) + len(cross_matter)
    print("\nFAIL" if bad else "\nPASS", f"- {bad} finding(s)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
