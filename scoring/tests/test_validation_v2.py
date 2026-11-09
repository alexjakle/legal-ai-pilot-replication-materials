"""Tests for validation set v2 (W01..W40): composition, bases, blindness of items.jsonl, determinism. Data only;
no model calls. v1 files are read, never written."""
import collections
import importlib.util
import json
import os
import re
import sys

import pytest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VAL = os.path.join(HERE, "validation")
V2 = os.path.join(VAL, "v2")
sys.path.insert(0, VAL)

import vlib  # noqa: E402
from judge.util import read_jsonl  # noqa: E402

RUNS = os.path.join(HERE, "..", "pipeline", "runs")
needs_runs = pytest.mark.skipif(not os.path.isdir(RUNS), reason="../pipeline/runs not present")


def _load(name):
    key = "v2_" + name
    if key in sys.modules:
        return sys.modules[key]
    spec = importlib.util.spec_from_file_location(key, os.path.join(V2, name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[key] = mod
    spec.loader.exec_module(mod)
    return mod


REGISTRY = read_jsonl(os.path.join(HERE, "registry.jsonl"))
REG = {r["id"]: r for r in REGISTRY}
ITEMS = read_jsonl(os.path.join(V2, "items.jsonl"))
LABELS = read_jsonl(os.path.join(V2, "construction", "labels.jsonl"))
PLAN = json.load(open(os.path.join(V2, "construction", "plan.json"), encoding="utf-8"))
INSERTS = read_jsonl(os.path.join(V2, "construction", "inserts.jsonl"))
V1_PLAN = json.load(open(os.path.join(VAL, "construction", "plan.json"), encoding="utf-8"))
V1_INSERTS = read_jsonl(os.path.join(VAL, "construction", "inserts.jsonl"))
NEAR_MD = open(os.path.join(HERE, "near_misses.md"), encoding="utf-8").read()
KINDS = dict(verbatim=4, paraphrase=6, client_pattern=8, area_pattern=6, multi=2, lookalike=10, none=4)


def test_item_ids_and_file_shape():
    assert [i["id"] for i in ITEMS] == ["W%02d" % n for n in range(1, 41)]
    assert all(sorted(i) == ["id", "text"] for i in ITEMS)


def test_items_carry_no_ids_conditions_or_slots():
    blob = " ".join(i["text"] for i in ITEMS)
    for s in PLAN["slots"]:
        assert s["base"]["run_id"] not in blob and s["base"]["probe_id"] not in blob
    for r in REGISTRY:
        assert not re.search(r"\b%s\b" % re.escape(r["id"]), blob), r["id"]
    raw = open(os.path.join(V2, "items.jsonl"), encoding="utf-8").read()
    for token in ("condition", "probe_id", "run_id", "slot", "kind", "registry"):
        assert '"%s"' % token not in raw


def test_composition():
    assert collections.Counter(l["kind"] for l in LABELS) == KINDS
    assert len(PLAN["slots"]) == 40 and len(LABELS) == 40
    look = [l for l in LABELS if l["kind"] == "lookalike"]
    assert collections.Counter(l["near_miss"]["mode"] for l in look) == {"literal": 5, "reworded": 5}
    assert collections.Counter(l["near_miss"]["family"] for l in look if l["near_miss"]["mode"] == "reworded") == \
        {"C2": 1, "C1": 1, "A2": 1, "P1": 1, "P2": 1}
    types = collections.Counter(REG[e["row"]]["type"] for l in LABELS if l["kind"] != "multi" for e in l["expected"])
    assert types == {"verbatim": 4, "paraphrase": 6, "client_pattern": 8, "area_pattern": 6}
    assert {vlib.family_of(e["row"]) for l in LABELS if l["kind"] == "area_pattern" for e in l["expected"]} == {"P1", "P2"}
    assert not [l for l in LABELS if l["kind"] in ("none", "lookalike") and l["expected"]]


def test_multi_rows():
    multi = [l for l in LABELS if l["kind"] == "multi"]
    assert len(multi) == 2
    seen = set()
    for l in multi:
        a, b = [REG[e["row"]] for e in l["expected"]]
        assert a["type"] != b["type"] and a["intended_reach"] != b["intended_reach"]
        assert not seen & {a["id"], b["id"]}
        seen |= {a["id"], b["id"]}
        assert len(l["inserted_text"]) == 2


def test_literal_lookalikes_are_quotes_not_used_in_v1():
    v1_norm = [vlib.norm(o["text"]) for it in V1_INSERTS for o in it["inserts"]]
    quotes = [q["quote"] for q in vlib.parse_near_misses(NEAR_MD)]
    lits = [l for l in LABELS if l["kind"] == "lookalike" and l["near_miss"]["mode"] == "literal"]
    sections = []
    for l in lits:
        text = vlib.norm(l["inserted_text"][0])
        hit = [q for q in quotes if vlib.norm(q).rstrip(".") in text]
        assert len(hit) == 1
        assert not any(vlib.norm(hit[0]).rstrip(".") in t for t in v1_norm)
        sections.append(next(q["section"] for q in vlib.parse_near_misses(NEAR_MD) if q["quote"] == hit[0]))
    assert len(set(sections)) == 5


def test_reworded_lookalikes_are_the_approved_drafts():
    cb = _load("choose_bases")
    drafts = cb.parse_drafts(open(os.path.join(V2, "drafts", "lookalikes_reworded.md"), encoding="utf-8").read())
    got = sorted(vlib.norm(l["inserted_text"][0]) for l in LABELS
                 if l["kind"] == "lookalike" and l["near_miss"]["mode"] == "reworded")
    assert got == sorted(vlib.norm(d["text"]) for d in drafts) and len(drafts) == 5


def test_lookalikes_carry_no_unique_detection_key_and_reworded_none_at_all():
    own = " ".join(r["text"].lower() for r in REGISTRY) + NEAR_MD.lower()
    unique = [k for r in REGISTRY for k in r["detection_keys"] if k.lower() not in own]
    for l in LABELS:
        if l["kind"] != "lookalike":
            continue
        text = l["inserted_text"][0].lower()
        assert not [k for k in unique if k.lower() in text]
        if l["near_miss"]["mode"] == "reworded":
            assert not any(vlib.key_hits(text, r) for r in REGISTRY)
        assert len(vlib._boundaries(l["inserted_text"][0])) <= 2


def test_inserts_present_and_row_rules():
    for l, it in zip(LABELS, ITEMS):
        assert l["id"] == it["id"]
        for t in l["inserted_text"]:
            assert t.strip() in it["text"]
        for e in l["expected"]:
            row = REG[e["row"]]
            assert e["strength"] == vlib.STRENGTH[row["type"]]
            text = " ".join(l["inserted_text"])
            if row["type"] == "verbatim":
                assert vlib.exact_hit(text, row)
            else:
                assert not vlib.key_hits(text, row)
        if l["kind"] == "none":
            assert not l["inserted_text"]


def test_inserted_sentences_do_not_echo_v1():
    cb = _load("choose_bases")  # noqa: F841
    b = _load("build")
    v1 = set().union(*[b.ngrams(o["text"]) for it in V1_INSERTS for o in it["inserts"]])
    v1_six = set().union(*[b.ngrams(o["text"], 6) for it in V1_INSERTS for o in it["inserts"]])
    for l in LABELS:
        reworded = l["kind"] == "lookalike" and l["near_miss"]["mode"] == "reworded"
        for t in l["inserted_text"]:
            # approved reworded drafts are held to the build's looser 6-word rule, everything else to 5
            assert not (b.ngrams(t, 6) & v1_six if reworded else b.ngrams(t) & v1)


@needs_runs
def test_bases_not_reused_from_v1_and_probe_cap():
    v1_used = {(s["base"]["run_id"], s["base"]["probe_id"]) for s in V1_PLAN["slots"]}
    bases = [(l["base"]["run_id"], l["base"]["probe_id"]) for l in LABELS]
    assert len(set(bases)) == 40 and not set(bases) & v1_used
    assert max(collections.Counter(p for _, p in bases).values()) <= 2
    cb = _load("choose_bases")
    pool = {(b["run_id"], b["probe_id"]): b for b in cb.load_pool()}
    for l in LABELS:
        b = pool[(l["base"]["run_id"], l["base"]["probe_id"])]
        assert l["base"]["condition"] == b["condition"] and 200 <= b["words"] <= 600
        assert vlib.word_count(b["text"]) == l["base"]["words"]
    src = collections.Counter(l["base"]["condition"] == "N0" for l in LABELS)
    assert src == {True: 30, False: 10}
    assert {l["base"]["run_id"] for l in LABELS if l["base"]["condition"] == "N0"} <= set(cb.N0_RUNS)
    assert {l["base"]["condition"] for l in LABELS} <= {"N0", "C0", "C1", "C2"}


@needs_runs
def test_usable_rule_holds_for_every_base():
    cb = _load("choose_bases")
    pool = {(b["run_id"], b["probe_id"]): b for b in cb.load_pool()}
    for l in LABELS:
        b = pool[(l["base"]["run_id"], l["base"]["probe_id"])]
        rows = [REG[e["row"]] for e in l["expected"]]
        if l["kind"] in ("lookalike", "none"):
            assert not any(vlib.exact_hit(b["text"], r) for r in REGISTRY)
        else:
            assert not any(vlib.exact_hit(b["text"], r) or vlib.key_hits(b["text"], r) for r in rows)


@needs_runs
def test_build_is_deterministic_for_the_seed(tmp_path):
    b = _load("build")
    out = tmp_path / "v2"
    b.main(["--out", str(out)])
    for name in ("items.jsonl", os.path.join("construction", "inserts.jsonl"), os.path.join("construction", "labels.jsonl")):
        assert open(out / name, encoding="utf-8").read() == open(os.path.join(V2, name), encoding="utf-8").read()


@needs_runs
def test_choose_bases_is_deterministic_for_the_seed(tmp_path, monkeypatch):
    cb = _load("choose_bases")
    cb_load_pool = cb.load_pool   # the real function, kept before the patch
    before = open(cb.PLAN, encoding="utf-8").read()
    # pin to the runs the frozen v2 set was built from: the two N0 runs plus the three original C runs
    pinned = tmp_path / "pinned_runs"
    pinned.mkdir()
    for n in tuple(cb.N0_RUNS) + ("20261019T230656Z_C1", "20261019T231541Z_C2", "20261019T232425Z_C0"):
        os.symlink(os.path.join(RUNS, n), str(pinned / n))
    monkeypatch.setattr(cb, "load_pool", lambda: cb_load_pool(str(pinned)))
    monkeypatch.setattr(cb, "PLAN", str(tmp_path / "plan.json"))
    cb.main()
    assert open(tmp_path / "plan.json", encoding="utf-8").read() == before
    assert json.loads(before)["seed"] == 20261028


def test_v1_files_untouched_by_v2_paths():
    for p in ("items.jsonl", "labels.csv"):
        assert os.path.exists(os.path.join(VAL, p))
    assert os.path.dirname(os.path.join(V2, "items.jsonl")) != VAL
