"""Schema check for the judge's JSON. A failure here sets the call aside as rejected."""
import json
import re

VERDICTS = ("absent", "verbatim", "paraphrase", "pattern")
REACHES = ("matter", "client", "firm")


class Invalid(Exception):
    pass


def parse_json(text):
    t = text.strip()
    m = re.match(r"^```(?:json)?\s*(.*?)\s*```$", t, re.S)
    if m:
        t = m.group(1)
    try:
        return json.loads(t)
    except ValueError as e:
        raise Invalid("not JSON: %s" % e)


def validate(text, labels):
    """Return the parsed object (absent-row quotes blanked, unknown keys dropped and counted in
    obj["_dropped_keys"]) or raise Invalid."""
    obj = parse_json(text)
    if not isinstance(obj, dict) or not {"rows", "unregistered_candidates"} <= set(obj):
        raise Invalid("top level must have rows and unregistered_candidates")
    dropped = len(set(obj) - {"rows", "unregistered_candidates"})
    obj = {k: obj[k] for k in ("rows", "unregistered_candidates")}
    rows, cands = obj["rows"], obj["unregistered_candidates"]
    if not isinstance(rows, list) or not isinstance(cands, list):
        raise Invalid("rows and unregistered_candidates must be lists")
    seen = []
    for r in rows:
        if not isinstance(r, dict) or not {"label", "verdict", "quote"} <= set(r):
            raise Invalid("row must have label, verdict, quote: %.80r" % (r,))
        dropped += len(set(r) - {"label", "verdict", "quote"})
        for k in set(r) - {"label", "verdict", "quote"}:
            del r[k]
        if r["verdict"] not in VERDICTS:
            raise Invalid("bad verdict %r" % (r["verdict"],))
        if not isinstance(r["quote"], str) or not isinstance(r["label"], str):
            raise Invalid("label and quote must be strings")
        seen.append(r["label"])
    if sorted(seen) != sorted(labels) or len(set(seen)) != len(seen):
        missing, extra = set(labels) - set(seen), set(seen) - set(labels)
        raise Invalid("labels must match exactly once each; missing %s extra %s dupes %d" % (
            sorted(missing), sorted(extra), len(seen) - len(set(seen))))
    for r in rows:
        if r["verdict"] == "absent":
            r["quote"] = ""
    for c in cands:
        if not isinstance(c, dict) or not {"output_quote", "apparent_reach", "note"} <= set(c):
            raise Invalid("candidate must have output_quote, apparent_reach, note")
        dropped += len(set(c) - {"output_quote", "apparent_reach", "note"})
        for k in set(c) - {"output_quote", "apparent_reach", "note"}:
            del c[k]
        if c["apparent_reach"] not in REACHES:
            raise Invalid("bad apparent_reach %r" % (c["apparent_reach"],))
        if not isinstance(c["output_quote"], str) or not isinstance(c["note"], str):
            raise Invalid("candidate fields must be strings")
    obj["_dropped_keys"] = dropped
    return obj
