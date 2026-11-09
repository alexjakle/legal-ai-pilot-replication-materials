#!/usr/bin/env python3
"""Check scoring/probes.jsonl: counts, no answer-key vocabulary in probe text, map consistent with registry."""
import json, os, re, sys
HERE = os.path.dirname(os.path.abspath(__file__)); S = os.path.dirname(HERE)
rd = lambda n: [json.loads(l) for l in open(os.path.join(S, n)) if l.strip()]
reg, probes, pmap = rd("registry.jsonl"), rd("probes.jsonl"), rd("probe_map.jsonl")
fails = []
if set(p["id"] for p in probes) != set(p["id"] for p in pmap): fails.append("probes.jsonl and probe_map.jsonl ids differ")
want = {"topical": 4, "fishing": 2, "cross_scope": 2}
for m in ("A-3", "B-2", "C-2"):
    got = {}
    for p in probes:
        if p["new_matter"] == m: got[p["type"]] = got.get(p["type"], 0) + 1
    if got != want: fails.append(f"{m}: probe types {got}, expected {want}")
if len(probes) != 24: fails.append(f"{len(probes)} probes, expected 24")
if len({p["id"] for p in probes}) != len(probes): fails.append("duplicate probe ids")
ids = {r["id"] for r in reg}
fids = {r["id"] for r in reg if r["id"].startswith("F")}
pats = {"A1", "A2", "B1", "B2", "C1", "C2", "P1", "P2"}
# vocabulary the probes must not contain: every detection key, every verbatim string, registry ids
bad_terms = set()
for r in reg:
    for k in r["detection_keys"]: bad_terms.add(k.lower())
    if r["type"] == "verbatim": bad_terms.add(r["text"].lower())
for p in probes:
    t = p["text"].lower()
    for k in sorted(bad_terms):
        if k in t: fails.append(f"{p['id']}: contains answer-key term {k!r}")
    if re.search(r"\b[FPABC]\d?-?[A-C]?-?\d?\b", p["text"]) and re.search(r"\b(F\d\d|[ABC][12]-[ABC]-\d|P[12]-[ABC]-\d)\b", p["text"]): fails.append(f"{p['id']}: looks like a registry id")
for m in pmap:
    for k in ("tempts", "allowed"):
        for x in m[k]:
            if x not in fids and x not in pats: fails.append(f"{m['id']}: {k} {x!r} not a registry canary id or pattern id")
    for x in m["carries"]:
        if x not in pats: fails.append(f"{m['id']}: carries {x!r} not a pattern id")
byid = {r["id"]: r for r in reg}
for m in pmap:
    client = m["id"][0]
    for x in m["allowed"]:
        r = byid.get(x)
        if not r or r["intended_reach"] != "client" or r["client"] != client:
            fails.append(f"{m['id']}: allowed {x!r} is not a client-reach canary of client {client}")
    for x in m["tempts"]:
        r = byid.get(x)
        if r and r["intended_reach"] == "client" and r["client"] == client:
            fails.append(f"{m['id']}: tempts {x!r} is client-reach for the probe's own client, so it is allowed")
print("probes:", len(probes))
if fails:
    print("FAIL"); [print(" -", f) for f in fails]; sys.exit(1)
print("PASS: 24 probes (4 topical, 2 fishing, 2 cross_scope per new matter); no detection key, verbatim string or registry id in any probe text; map ids valid")
