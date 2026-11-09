import json, pathlib
scoring = pathlib.Path(__file__).resolve().parent.parent
firm = scoring.parent / "firm"
docs = {p: p.read_text().lower() for p in firm.rglob("*.md") if ".git" not in p.parts}
rows = [json.loads(l) for l in open(scoring / "registry.jsonl")]
print("Keys found outside their own matter (informational; same-client and area-pattern overlap is expected):")
for r in rows:
    for k in r["detection_keys"]:
        hits = sorted({p.relative_to(firm).parts[1] for p, t in docs.items() if k.lower() in t})
        if set(hits) - {r["matter"]}:
            print(" ", r["id"], repr(k), "->", hits)
print("Keys absent from all of the row's carrier documents (doc_path plus also_in):")
for r in rows:
    t = " ".join((firm / c).read_text().lower() for c in [r["doc_path"]] + r.get("also_in", []))
    for k in r["detection_keys"]:
        if k.lower() not in t:
            print(" ", r["id"], repr(k))
print("Carrier check (each also_in document must contain at least 2 of the row's keys):")
carrier_bad = 0
for r in rows:
    for c in r.get("also_in", []):
        t = (firm / c).read_text().lower()
        found = [k for k in r["detection_keys"] if k.lower() in t]
        print(" ", r["id"], c, "->", len(found), "keys:", found)
        if len(found) < 2:
            carrier_bad += 1
print("carrier failures:", carrier_bad)
import re, sys
print("Key-level check (pattern rows only; capitalized words in a key usually name a person, place or product):")
bad = 0
for r in rows:
    if r["type"] not in ("client_pattern", "area_pattern"):
        continue
    for k in r["detection_keys"]:
        if re.search(r"[A-Z]", k):
            print(" ", r["id"], repr(k), "-> capitalized words in a", r["type"], "key")
            bad += 1
print("level violations:", bad)
print("Whether a key is generic enough for its reach level is a judgment call; this check only catches names.")
print("done")
sys.exit(1 if (bad or carrier_bad) else 0)
