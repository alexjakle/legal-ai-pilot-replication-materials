#!/usr/bin/env python3
"""Check scoring/registry.jsonl against ../firm (standard library only)."""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
FIRM = os.path.join(HERE, "..", "firm")
REGISTRY = os.path.join(HERE, "registry.jsonl")

FIELDS = {"id", "client", "matter", "type", "text", "detection_keys", "intended_reach", "doc_path"}
OPTIONAL = {"also_in"}  # client_pattern rows only: other documents (instruction letters) that carry the same instruction


def norm(s):
    return re.sub(r"\s+", " ", s).lower()


def main():
    rows = [json.loads(l) for l in open(REGISTRY) if l.strip()]
    docs = {}
    for root, _, files in os.walk(FIRM):
        for f in files:
            p = os.path.join(root, f)
            if ".git" in p.split(os.sep):
                continue
            rel = os.path.relpath(p, FIRM)
            docs[rel] = open(p, encoding="utf-8", errors="ignore").read()
    failures = []

    for r in rows:
        if (FIELDS - set(r)) or (set(r) - FIELDS - OPTIONAL):
            failures.append(f"{r.get('id')}: fields differ from schema: {sorted((FIELDS - set(r)) | (set(r) - FIELDS - OPTIONAL))}")
        if r["doc_path"] not in docs:
            failures.append(f"{r['id']}: doc_path missing: {r['doc_path']}")
        if "also_in" in r:
            if r["type"] != "client_pattern":
                failures.append(f"{r['id']}: also_in is allowed on client_pattern rows only")
            for c in r["also_in"]:
                if c not in docs:
                    failures.append(f"{r['id']}: also_in path missing: {c}")
                elif c == r["doc_path"]:
                    failures.append(f"{r['id']}: also_in repeats doc_path")
                elif os.path.dirname(c) != os.path.dirname(r["doc_path"]):
                    failures.append(f"{r['id']}: also_in {c} is outside the row's matter folder")

    for r in rows:
        if r["type"] == "verbatim":
            s = r["text"]
            hits = [p for p, t in docs.items() if t.count(s)]
            total = sum(t.count(s) for t in docs.values())
            if total != 1:
                failures.append(f"{r['id']}: {s!r} occurs {total} times across firm")
            elif hits[0] != r["doc_path"]:
                failures.append(f"{r['id']}: {s!r} found in {hits[0]}, not doc_path {r['doc_path']}")
            matter_dir = os.path.dirname(r["doc_path"])
            others = [p for p in hits if os.path.dirname(p) != matter_dir]
            if others:
                failures.append(f"{r['id']}: {s!r} appears in other matter(s): {others}")
        elif r["type"] == "paraphrase":
            body = norm(docs.get(r["doc_path"], ""))
            found = [k for k in r["detection_keys"] if norm(k) in body]
            if len(found) < 3:
                failures.append(f"{r['id']}: only {len(found)} of {len(r['detection_keys'])} detection keys in doc_path")

    counts = {}
    for r in rows:
        counts[r["type"]] = counts.get(r["type"], 0) + 1
    print("rows:", len(rows), counts)
    if failures:
        print("FAIL")
        for f in failures:
            print(" -", f)
        sys.exit(1)
    print("PASS: doc_paths exist; verbatim strings unique and matter-local; paraphrase rows have >=3 keys")


if __name__ == "__main__":
    main()
