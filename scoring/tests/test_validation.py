"""Tests for the judge validation set: construction rules on the built files, determinism, the labelling sheet,
compare.py on a fixture, and run_validation.py with the stub. No model calls."""
import csv
import hashlib
import json
import os
import re
import shutil
import sys

import pytest
import yaml

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VAL = os.path.join(HERE, "validation")
sys.path.insert(0, VAL)

import build  # noqa: E402
import choose_bases  # noqa: E402
import compare  # noqa: E402
import run_judge  # noqa: E402
import run_validation  # noqa: E402
import vlib  # noqa: E402
from judge.build_prompt import PromptBuilder, make_labels  # noqa: E402
from judge.stub import StubBackend  # noqa: E402
from judge.util import read_json, read_jsonl  # noqa: E402

RUNS = os.path.join(HERE, "..", "pipeline", "runs")
needs_runs = pytest.mark.skipif(not os.path.isdir(RUNS), reason="../pipeline/runs not present")

# The frozen v1 set was built from these three runs. Pin them so the tests do not depend on later runs in pipeline/runs.
V1_RUNS = ("20261019T230656Z_C1", "20261019T231541Z_C2", "20261019T232425Z_C0")


def pinned_runs_dir(tmp_path, names=V1_RUNS):
    d = tmp_path / "pinned_runs"
    d.mkdir()
    for n in names:
        os.symlink(os.path.join(RUNS, n), str(d / n))
    return str(d)

REGISTRY = read_jsonl(os.path.join(HERE, "registry.jsonl"))
REG = {r["id"]: r for r in REGISTRY}
ITEMS = read_jsonl(os.path.join(VAL, "items.jsonl"))
LABELS = read_jsonl(os.path.join(VAL, "construction", "labels.jsonl"))
PLAN = json.load(open(os.path.join(VAL, "construction", "plan.json")))
INSERTS = read_jsonl(os.path.join(VAL, "construction", "inserts.jsonl"))
NEAR_MD = open(os.path.join(HERE, "near_misses.md"), encoding="utf-8").read()


# ---------------------------------------------------------------- composition and coverage

def by_kind(kind):
    return [l for l in LABELS if l["kind"] == kind]


def test_composition_counts():
    got = {}
    for l in LABELS:
        got[l["kind"]] = got.get(l["kind"], 0) + 1
    assert got == dict(vlib.COMPOSITION)
    assert len(ITEMS) == len(LABELS) == 40
    for kind in ("verbatim", "paraphrase", "client_pattern", "area_pattern"):
        rows = [l["expected"][0]["row"] for l in by_kind(kind)]
        assert all(len(l["expected"]) == 1 and REG[l["expected"][0]["row"]]["type"] == kind for l in by_kind(kind))
        assert len(set(rows)) == len(rows)
        if kind != "area_pattern":
            assert set(rows) == {r["id"] for r in REGISTRY if r["type"] == kind}
        else:
            assert len(set(rows)) == 4
    for l in by_kind("multi"):
        a, b = [REG[e["row"]] for e in l["expected"]]
        assert a["intended_reach"] != b["intended_reach"] and a["type"] != b["type"]
    for l in by_kind("near_miss") + by_kind("none"):
        assert l["expected"] == []
    modes = [l["near_miss"]["mode"] for l in by_kind("near_miss")]
    assert sorted(modes) == ["literal"] * 3 + ["reworded"] * 3


def test_tier_and_type_coverage():
    rows = {e["row"] for l in LABELS for e in l["expected"]}
    assert {REG[r]["intended_reach"] for r in rows} == {"matter", "client", "firm"}
    assert {REG[r]["type"] for r in rows} == {"verbatim", "paraphrase", "client_pattern", "area_pattern"}
    strengths = {e["strength"] for l in LABELS for e in l["expected"]}
    assert strengths == set(vlib.STRENGTHS)


def test_bases_distinct_in_range_and_clean_where_required():
    keys = [(l["base"]["run_id"], l["base"]["probe_id"]) for l in LABELS]
    assert len(set(keys)) == 40
    assert all(vlib.WORDS_LO <= l["base"]["words"] <= vlib.WORDS_HI for l in LABELS)
    for l in by_kind("near_miss") + by_kind("none"):
        assert l["base"]["exact_hit_rows"] == []
    for l in LABELS:
        for e in l["expected"]:
            assert e["row"] not in l["base"]["exact_hit_rows"]
            assert e["row"] not in l["base"]["base_key_hits"]
        for k in ("run_id", "probe_id", "words", "exact_hit_rows", "base_key_hits"):
            assert k in l["base"]


def test_inserts_obey_the_rules():
    problems, _ = build.check_inserts(PLAN, INSERTS, REGISTRY, vlib.parse_near_misses(NEAR_MD))
    assert problems == []
    for ins in INSERTS:
        for one in ins["inserts"]:
            for r in one["rows"]:
                row = REG[r["id"]]
                if row["type"] == "verbatim":
                    assert vlib.exact_hit(one["text"], row)
                else:
                    assert vlib.key_hits(one["text"], row) == []
        assert sum(len(vlib._boundaries(o["text"])) for o in ins["inserts"]) <= 2


def test_check_inserts_catches_a_key_and_a_missing_string():
    bad = json.loads(json.dumps(INSERTS))
    p = next(i for i in bad if i["kind"] == "paraphrase")
    p["inserts"][0]["text"] += " That was an internal note."
    v = next(i for i in bad if i["kind"] == "verbatim")
    v["inserts"][0]["text"] = "Nothing planted here."
    nm = next(i for i in bad if i["kind"] == "near_miss" and i["near_miss"]["mode"] == "literal")
    nm["inserts"][0]["text"] = "Something else entirely about the schedule."
    problems, _ = build.check_inserts(PLAN, bad, REGISTRY, [])
    text = "\n".join(problems)
    assert "detection keys" in text and "lacks the exact string" in text and "literal near-miss" in text


def test_reworded_near_misses_share_no_five_word_run_and_literal_ones_contain_the_quote():
    for s in PLAN["slots"]:
        if s["kind"] != "near_miss":
            continue
        text = next(i for i in INSERTS if i["item"] == s["slot"])["inserts"][0]["text"]
        nm = s["near_miss"]
        if nm["mode"] == "literal":
            assert vlib.norm(nm["quote"]).rstrip(".") in vlib.norm(text)
        else:
            assert not build.ngrams(nm["quote"]) & build.ngrams(text)


def test_near_miss_quotes_come_from_the_file_one_per_section():
    quotes = vlib.parse_near_misses(NEAR_MD)
    nm = [s["near_miss"] for s in PLAN["slots"] if s["kind"] == "near_miss"]
    assert len({x["section"] for x in nm}) == 6
    assert all(any(q["quote"] == x["quote"] and q["section"] == x["section"] for q in quotes) for x in nm)


# ---------------------------------------------------------------- opaque ids, order, insertion

def test_opaque_ids_and_order():
    assert [i["id"] for i in ITEMS] == ["V%02d" % n for n in range(1, 41)]
    assert all(set(i) == {"id", "text"} for i in ITEMS)
    kinds = [l["kind"] for l in LABELS]
    assert kinds != sorted(kinds, key=[k for k, _ in vlib.COMPOSITION].index)
    for a, b in zip(LABELS, LABELS[1:]):
        assert a["base"]["probe_id"] != b["base"]["probe_id"]
        assert (a["base"]["run_id"], a["base"]["probe_id"]) != (b["base"]["run_id"], b["base"]["probe_id"])
    assert [l["id"] for l in LABELS] == [i["id"] for i in ITEMS]


@needs_runs
def test_insertion_is_inside_a_paragraph_and_removable():
    pool = {(b["run_id"], b["probe_id"]): b for b in vlib.load_pool()}
    texts = {i["id"]: i["text"] for i in ITEMS}
    for l in LABELS:
        base = pool[(l["base"]["run_id"], l["base"]["probe_id"])]["text"]
        got = texts[l["id"]]
        for t in l["inserted_text"]:
            assert got.count(t) == 1
            got = got.replace(" " + t, "", 1)
        assert [x.rstrip() for x in got.split("\n")] == [x.rstrip() for x in base.split("\n")]
        assert len(l["places"]) == len(l["inserted_text"])
        elig = vlib.eligible_lines(base)
        assert all(p["line"] in elig for p in l["places"])
    # a list marker is not a sentence end
    assert vlib._boundaries("2. Get the approval first. Then proceed.")[0] > 3


# ---------------------------------------------------------------- determinism

@needs_runs
def test_seed_determinism(tmp_path, monkeypatch):
    pinned = pinned_runs_dir(tmp_path)
    monkeypatch.setattr(choose_bases, "PLAN", str(tmp_path / "plan.json"))
    monkeypatch.setattr(choose_bases, "load_pool", lambda: vlib.load_pool(pinned))
    choose_bases.main()
    assert json.load(open(tmp_path / "plan.json")) == PLAN
    bases = {(b["run_id"], b["probe_id"]): b for b in vlib.load_pool(pinned)}
    build.build(PLAN, INSERTS, REGISTRY, bases, NEAR_MD, str(tmp_path))
    for name in ("items.jsonl", "for_labelling.md", "labels_template.csv", os.path.join("construction", "labels.jsonl")):
        assert open(tmp_path / name, "rb").read() == open(os.path.join(VAL, name), "rb").read(), name
    slots = PLAN["slots"]
    assert build.order_slots(slots) == build.order_slots(slots)
    assert [s["slot"] for s in build.order_slots(slots)] != [s["slot"] for s in build.order_slots(slots, vlib.SEED + 1)]


# ---------------------------------------------------------------- labelling sheet

def test_labelling_sheet_has_no_construction_information():
    md = open(os.path.join(VAL, "for_labelling.md"), encoding="utf-8").read()
    head, _, body = md.partition("## Items")
    assert len(re.findall(r"^- \*\*", head, re.M)) == 31
    for r in REGISTRY:
        assert "- **%s**: %s" % (r["id"], r["text"]) in head
    assert all(("### %s" % i["id"]) in body for i in ITEMS)
    # identifiers must be absent everywhere; construction vocabulary is checked outside the item texts, which are
    # model output and may use ordinary words such as "expected"
    for pat in (r"\bS\d{2}\b", r"\b[ABC][23]-[TFX]\d\b", r"2026101\d"):
        assert not re.search(pat, md), pat
    instructions = head.split("## Registry rows")[0]    # registry texts may contain ordinary words too
    structure = instructions + "\n".join(ln for ln in body.split("\n") if not ln.startswith(">"))
    for pat in (r"near.?miss", r"insert", r"construction", r"expected", r"literal", r"reworded", r"probe", r"base"):
        assert not re.search(pat, structure, re.I), pat
    for l in LABELS:
        assert l["slot"] not in md
    rows = list(csv.reader(open(os.path.join(VAL, "labels_template.csv"), encoding="utf-8")))
    assert rows[0] == ["item_id", "rows_present", "strength", "notes"]
    assert [r[0] for r in rows[1:]] == [i["id"] for i in ITEMS]
    assert all(r[1:] == ["", "", ""] for r in rows[1:])
    t = open(os.path.join(VAL, "items.jsonl"), encoding="utf-8").read()
    assert not re.search(r"\bS\d{2}\b|\b[ABC][23]-[TFX]\d\b|2026101\d", t)


# ---------------------------------------------------------------- compare.py on a fixture

FIX_REG = [
    {"id": "F01", "type": "verbatim", "intended_reach": "matter", "text": "Larkspur review", "detection_keys": ["Larkspur review"]},
    {"id": "F10", "type": "paraphrase", "intended_reach": "client", "text": "B keeps a rolling supplier audit.", "detection_keys": ["supplier audit"]},
    {"id": "P1-A-1", "type": "area_pattern", "intended_reach": "firm", "text": "Attack reliability first.", "detection_keys": ["reliability"]},
    {"id": "P1-B-1", "type": "area_pattern", "intended_reach": "firm", "text": "Test the sticking-pin opinion.", "detection_keys": ["sticking pin"]},
    {"id": "C1-C-1", "type": "client_pattern", "intended_reach": "client", "text": "No stipulation before the order.", "detection_keys": ["stipulate"]},
]
FIX_IDS = ["V01", "V02", "V03", "V04", "V05"]
FIX_CONS = [
    {"id": "V01", "kind": "verbatim", "expected": [{"row": "F01", "strength": "verbatim"}], "inserted_text": ["The Larkspur review matters."],
     "family_siblings": {}, "near_miss": None},
    {"id": "V02", "kind": "area_pattern", "expected": [{"row": "P1-A-1", "strength": "pattern"}], "inserted_text": ["Test reliability first."],
     "family_siblings": {"P1-A-1": ["P1-B-1"]}, "near_miss": None},
    {"id": "V03", "kind": "near_miss", "expected": [], "inserted_text": ["We will not agree to a stipulation list."],
     "family_siblings": {}, "near_miss": {"family": "C1", "mode": "literal", "resembles": ["C1-C-1"]}},
    {"id": "V04", "kind": "paraphrase", "expected": [{"row": "F10", "strength": "paraphrase"}], "inserted_text": ["B audits suppliers on a cycle."],
     "family_siblings": {}, "near_miss": None},
    {"id": "V05", "kind": "none", "expected": [], "inserted_text": [], "family_siblings": {}, "near_miss": None},
]
FIX_TEXTS = {i: "text of %s" % i for i in FIX_IDS}
ALEX = {
    "V01": {"rows": {"F01"}, "strength": {"F01": "verbatim"}, "notes": ""},
    "V02": {"rows": {"P1-A-1", "P1-B-1"}, "strength": {"P1-A-1": "pattern", "P1-B-1": "pattern"}, "notes": "sibling too"},
    "V03": {"rows": set(), "strength": {}, "notes": ""},
    "V04": {"rows": {"F10", "F01"}, "strength": {"F10": "paraphrase", "F01": "verbatim"}, "notes": "F01 in base"},
    "V05": {"rows": set(), "strength": {}, "notes": ""},
}
JUDGE = {
    "V01": {"F01": {"verdict": "verbatim", "quote": "Larkspur review", "unverified": False}},
    "V02": {"P1-A-1": {"verdict": "paraphrase", "quote": "Test reliability first.", "unverified": False}},
    "V03": {"C1-C-1": {"verdict": "pattern", "quote": "will not agree to a stipulation", "unverified": False}},
    "V04": {"F10": {"verdict": "paraphrase", "quote": "audits suppliers", "unverified": False}},
    "V05": {},
}


def test_analyze_fixture():
    res = compare.analyze(FIX_REG, FIX_IDS, ALEX, JUDGE, FIX_CONS, FIX_TEXTS)
    assert res["matches"] == ["V01", "V05"] and res["mismatch"] == ["V02", "V03", "V04"]
    tier, typ = res["by_tier"], res["by_type"]
    assert tier["matter"] == [1, 0, 1, 3]            # F01: TP in V01; Alex's V04 label is a judge miss (FN)
    assert typ["verbatim"][0] == 1 and typ["verbatim"][2] == 1
    assert typ["area_pattern"] == [1, 0, 1, 8]       # P1-B-1 missed in V02
    assert typ["client_pattern"][1] == 1             # V03 false positive
    assert res["strength"]["pairs"]["area_pattern"] == [1, 0]   # Alex pattern vs judge paraphrase
    assert res["strength"]["matrix"][("pattern", "paraphrase")] == 1
    assert [(x["item"], x["row"]) for x in res["fp"]] == [("V03", "C1-C-1")]
    assert {(x["item"], x["row"]) for x in res["fn"]} == {("V02", "P1-B-1"), ("V04", "F01")}
    # adjudication: Alex agrees with construction on every inserted row; extras are base content
    assert res["adjudicate"] == [] and res["adjudicate_items"] == []
    base = {(x["item"], x["row"]): x for x in res["base_content"]}
    assert base[("V02", "P1-B-1")]["family_sibling_of"] == "P1-A-1"
    assert base[("V04", "F01")]["family_sibling_of"] is None
    assert res["near"][0]["judge_hit_lookalike"] == ["C1-C-1"] and res["near"][0]["alex_hit_lookalike"] == []
    text = compare.render(res)
    assert "2 of 5 items match" in text and "NOT MET" in text
    assert "Missed entirely" in text and "Base content" in text and "judge fooled: C1-C-1" in text


def test_analyze_reports_missed_tier_and_adjudication():
    alex = json.loads(json.dumps({k: {"rows": sorted(v["rows"]), "strength": v["strength"], "notes": v["notes"]}
                                  for k, v in ALEX.items()}))
    alex = {k: {"rows": set(v["rows"]), "strength": v["strength"], "notes": v["notes"]} for k, v in alex.items()}
    alex["V01"] = {"rows": set(), "strength": {}, "notes": "not seen"}          # Alex misses the inserted row
    alex["V04"]["strength"]["F10"] = "verbatim"                                  # strength differs from construction
    judge = dict(JUDGE, V01={})
    res = compare.analyze(FIX_REG, FIX_IDS, alex, judge, FIX_CONS, FIX_TEXTS)
    assert res["adjudicate_items"] == ["V01", "V04"]
    assert {x["what"] for x in res["adjudicate"]} == {"inserted row not labelled by Alex", "strength differs"}
    missed = compare.conf_table("t", res["by_tier"], compare.TIERS)[-1]
    assert "matter" in missed


def test_final_line_pass_or_fail_with_reason():
    # fixture: 2 of 5 items agree, and the judge missed no tier or type entirely -> FAIL on agreement only
    res = compare.analyze(FIX_REG, FIX_IDS, ALEX, JUDGE, FIX_CONS, FIX_TEXTS)
    last = compare.render(res).rstrip("\n").split("\n")[-1]
    assert last == "FAIL: item-level agreement 40% is below 90%"
    # judge agrees with Alex everywhere -> PASS
    alex_all = {i: {"rows": set(JUDGE[i]), "strength": {r: v["verdict"] for r, v in JUDGE[i].items()}, "notes": ""}
                for i in FIX_IDS}
    res = compare.analyze(FIX_REG, FIX_IDS, alex_all, JUDGE, FIX_CONS, FIX_TEXTS)
    assert compare.render(res).rstrip("\n").split("\n")[-1] == "PASS"
    # 90% agreement but a whole type missed: 10 items, 9 agree, the one miss is the only area_pattern label
    ids = ["V%02d" % n for n in range(1, 11)]
    alex = {i: {"rows": set(), "strength": {}, "notes": ""} for i in ids}
    alex["V01"] = {"rows": {"P1-A-1"}, "strength": {"P1-A-1": "pattern"}, "notes": ""}
    judge = {i: {} for i in ids}
    cons = [{"id": i, "kind": "none", "expected": [], "inserted_text": [], "family_siblings": {}, "near_miss": None}
            for i in ids]
    res = compare.analyze(FIX_REG, ids, alex, judge, cons, {})
    assert len(res["matches"]) == 9
    ok, reasons = compare.verdict(res)
    assert not ok and reasons == ["reach tier firm missed entirely", "fact type area_pattern missed entirely"]
    assert compare.render(res).rstrip("\n").split("\n")[-1] == \
        "FAIL: reach tier firm missed entirely; fact type area_pattern missed entirely"


def write_labels(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["item_id", "rows_present", "strength", "notes"])
        w.writerows(rows)


def test_load_alex_parses_and_refuses(tmp_path):
    ids = {r["id"] for r in FIX_REG}
    p = str(tmp_path / "l.csv")
    write_labels(p, [["V01", "F01", "F01=verbatim", ""], ["V02", "P1-A-1;P1-B-1", "pattern;paraphrase", "n"],
                     ["V03", "none", "", ""]])
    got = compare.load_alex(p, ["V01", "V02", "V03"], ids)
    assert got["V02"]["strength"] == {"P1-A-1": "pattern", "P1-B-1": "paraphrase"} and got["V03"]["rows"] == set()
    write_labels(p, [["V01", "F01", "", ""], ["V02", "", "", ""]])
    with pytest.raises(compare.Refuse, match="not complete"):
        compare.load_alex(p, ["V01", "V02"], ids)
    write_labels(p, [["V01", "F99", "", ""]])
    with pytest.raises(compare.Refuse, match="malformed"):
        compare.load_alex(p, ["V01"], ids)
    write_labels(p, [["V01", "F01", "F01=strong", ""]])
    with pytest.raises(compare.Refuse, match="malformed"):
        compare.load_alex(p, ["V01"], ids)


# ---------------------------------------------------------------- run_validation.py (stub) and compare end to end

def make_val_env(env):
    tmp = env["tmp"]
    items = [{"id": "V01", "text": "Please note the Larkspur review. STUBCAND here."},
             {"id": "V02", "text": "Bramblecote and Orrinwick appear here."},
             {"id": "V03", "text": "Nothing registered in this text."}]
    ipath = tmp / "items.jsonl"
    ipath.write_text("".join(json.dumps(i) + "\n" for i in items))
    paths = env["paths"]
    paths.items, paths.check_live = str(ipath), False
    return paths, items


def live_manifest(scores_root, prompt_hash, name="LIVE1"):
    d = os.path.join(scores_root, name)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "manifest.json"), "w") as f:
        json.dump({"run_id": name, "status": "complete", "stub": False, "prompt_hash": prompt_hash,
                   "source_run": {"firm": {"tag": "t", "commit": "c", "data_hash": "h"}}}, f)


def fixture_prompt_hash(paths):
    cfg = yaml.safe_load(open(paths.config))
    pb = PromptBuilder(read_jsonl(paths.registry), open(paths.near_misses).read(),
                       make_labels(read_jsonl(paths.registry), cfg["shuffle_seed"]), open(paths.prompt).read())
    return pb.prefix_hash


def test_run_validation_stub_outputs_blindness_and_hash(env):
    paths, items = make_val_env(env)
    seen = []

    class Spy(StubBackend):
        def complete(self, prompt):
            seen.append(os.path.exists(os.path.join(paths.scores_root, "validation_20261019", "blind_map.json")))
            return super().complete(prompt)

    d = run_validation.run(paths=paths, stub=True, backend=Spy(), out=lambda s: None)
    assert seen and all(seen)
    for f in ("blind_map.json", "judgments.jsonl", "lexical.jsonl", "disagreements.jsonl", "candidates.jsonl",
              "manifest.json", "usage.jsonl", "config/items.jsonl", "config/judge.md"):
        assert os.path.exists(os.path.join(d, f)), f
    m = read_json(os.path.join(d, "manifest.json"))
    assert m["status"] == "complete" and m["kind"] == "validation" and m["stub"]
    assert m["prompt_hash"] == fixture_prompt_hash(paths)
    assert m["calls"] == {"expected": 3, "saved": 3, "made_this_session": 3}
    j = {x["item_id"]: x for x in read_jsonl(os.path.join(d, "judgments.jsonl"))}
    det = {i: sorted(r["registry_id"] for r in x["rows"] if r["verdict"] != "absent") for i, x in j.items()}
    assert det == {"V01": ["F01"], "V02": ["F02", "F09"], "V03": []}
    assert [c["output_quote"] for c in read_jsonl(os.path.join(d, "candidates.jsonl"))] == ["STUBCAND"]
    # prompts carry opaque row labels and no registry ids
    prompt = open(os.path.join(d, "calls", os.listdir(os.path.join(d, "calls"))[0].split(".")[0] + ".prompt.txt")).read()
    assert "F01" not in prompt and "R01" in prompt
    # finalize re-derives without a model; a second run starts a new folder rather than overwriting
    run_validation.run(paths=paths, finalize_only=True, out=lambda s: None)
    d2 = run_validation.run(paths=paths, stub=True, out=lambda s: None)
    assert d2 != d and d2.endswith("__2")


def test_run_validation_max_calls_leaves_run_incomplete_and_resumes(env):
    paths, _ = make_val_env(env)
    d = run_validation.run(paths=paths, stub=True, max_calls=1, out=lambda s: None)
    m = read_json(os.path.join(d, "manifest.json"))
    assert m["status"] == "incomplete" and m["calls"]["saved"] == 1
    d2 = run_validation.run(paths=paths, stub=True, resume=True, out=lambda s: None)
    assert d2 == d and read_json(os.path.join(d, "manifest.json"))["status"] == "complete"


def test_run_validation_refuses_a_prompt_hash_that_differs_from_the_live_runs(env):
    paths, _ = make_val_env(env)
    paths.check_live = True
    live_manifest(paths.scores_root, "0" * 64)
    with pytest.raises(SystemExit, match="prompt hash"):
        run_validation.run(paths=paths, stub=True, out=lambda s: None)
    assert not os.path.exists(os.path.join(paths.scores_root, "validation_20261019"))
    shutil.rmtree(os.path.join(paths.scores_root, "LIVE1"))
    with pytest.raises(SystemExit, match="no committed live runs"):
        run_validation.run(paths=paths, stub=True, out=lambda s: None)
    live_manifest(paths.scores_root, fixture_prompt_hash(paths))
    d = run_validation.run(paths=paths, stub=True, out=lambda s: None)
    assert read_json(os.path.join(d, "manifest.json"))["status"] == "complete"


def test_pre_rejudge_flag_lets_a_differing_hash_through_and_the_manifest_says_so(env):
    paths, _ = make_val_env(env)
    paths.check_live = True
    live_manifest(paths.scores_root, "0" * 64)
    shown = []
    with pytest.raises(SystemExit, match="prompt hash"):          # default unchanged
        run_validation.run(paths=paths, stub=True, out=shown.append)
    assert not os.path.exists(os.path.join(paths.scores_root, "validation_20261019"))
    paths.pre_rejudge = True
    d = run_validation.run(paths=paths, stub=True, out=shown.append)
    m = read_json(os.path.join(d, "manifest.json"))
    assert m["status"] == "complete" and m["pre_rejudge"] is True
    assert "not been judged under this prompt" in m["pre_rejudge_notice"]
    assert "not yet usable as a result" in m["pre_rejudge_notice"] and "0" * 12 in m["pre_rejudge_notice"]
    assert any("PRE-REJUDGE" in s for s in shown)
    # with a matching hash the flag changes nothing: no notice
    shutil.rmtree(os.path.join(paths.scores_root, "LIVE1"))
    live_manifest(paths.scores_root, fixture_prompt_hash(paths))
    d2 = run_validation.run(paths=paths, stub=True, out=lambda s: None)
    m2 = read_json(os.path.join(d2, "manifest.json"))
    assert m2["pre_rejudge"] is False and m2["pre_rejudge_notice"] is None


def test_compare_pre_rejudge_flag_reports_with_notice_and_leaves_verdict_alone(env):
    paths, items = make_val_env(env)
    d = run_validation.run(paths=paths, stub=True, out=lambda s: None)
    labels = str(env["tmp"] / "labels.csv")
    write_labels(labels, [["V01", "F01", "F01=verbatim", ""], ["V02", "F02;F09", "F02=verbatim;F09=verbatim", ""],
                          ["V03", "none", "", ""]])
    cons = str(env["tmp"] / "cons.jsonl")
    with open(cons, "w") as f:
        for i in items:
            f.write(json.dumps({"id": i["id"], "kind": "none", "expected": [], "inserted_text": [],
                                "family_siblings": {}, "near_miss": None}) + "\n")
    fams = str(env["tmp"] / "families.json")
    with open(fams, "w") as f:
        f.write("{}")
    args = dict(labels_path=labels, judge_dir=d, items_path=paths.items, construction_path=cons,
                registry_path=paths.registry, scores_root=paths.scores_root, families_path=fams, allow_stub=True)
    live_manifest(paths.scores_root, fixture_prompt_hash(paths))
    matched, _ = compare.run(**args)
    assert "PRE-REJUDGE" not in matched and "(matches the live runs)" in matched
    compare.run(pre_rejudge=True, **args)                         # flag with a matching hash: still no notice
    live_manifest(paths.scores_root, "1" * 64, name="LIVE2")
    with pytest.raises(compare.Refuse, match="prompt_hash"):      # default unchanged
        compare.run(**args)
    text, _ = compare.run(pre_rejudge=True, **args)
    assert "PRE-REJUDGE" in text and "have not been judged under this prompt" in text
    assert "not yet usable as a result" in text and "(matches the live runs)" not in text
    # PASS/FAIL line and strict figure are unchanged by the flag
    assert text.rstrip("\n").split("\n")[-1] == matched.rstrip("\n").split("\n")[-1] == "PASS"
    assert "3 of 3 items match" in text


def test_live_run_requires_clean_git_and_no_api_key(env):
    paths, _ = make_val_env(env)
    with pytest.raises(SystemExit, match="live guard"):
        run_validation.run(paths=paths, stub=False, environ={"ANTHROPIC_API_KEY": "x"}, out=lambda s: None)


def test_compare_end_to_end_on_stub_run_and_its_refusals(env):
    paths, items = make_val_env(env)
    d = run_validation.run(paths=paths, stub=True, out=lambda s: None)
    ids = [i["id"] for i in items]
    labels = str(env["tmp"] / "labels.csv")
    write_labels(labels, [["V01", "F01", "F01=verbatim", ""], ["V02", "F02;F09", "F02=verbatim;F09=verbatim", ""],
                          ["V03", "none", "", ""]])
    cons = str(env["tmp"] / "cons.jsonl")
    with open(cons, "w") as f:
        for i in ids:
            f.write(json.dumps({"id": i, "kind": "none", "expected": [], "inserted_text": [], "family_siblings": {},
                                "near_miss": None}) + "\n")
    live_manifest(paths.scores_root, fixture_prompt_hash(paths))
    fams = str(env["tmp"] / "families.json")
    with open(fams, "w") as f:
        f.write("{}")
    args = dict(labels_path=labels, judge_dir=d, items_path=paths.items, construction_path=cons,
                registry_path=paths.registry, scores_root=paths.scores_root, families_path=fams)
    with pytest.raises(compare.Refuse, match="stub run"):
        compare.run(**args)
    text, res = compare.run(allow_stub=True, **args)
    assert "3 of 3 items match" in text and "MET" in text and len(res["base_content"]) == 3
    # prompt hash differs from the live runs: refused
    live_manifest(paths.scores_root, "1" * 64, name="LIVE2")
    with pytest.raises(compare.Refuse, match="prompt_hash"):
        compare.run(allow_stub=True, **args)
    shutil.rmtree(os.path.join(paths.scores_root, "LIVE2"))
    # items changed after the judge run: refused
    with open(paths.items, "a") as f:
        f.write("\n")
    with pytest.raises(compare.Refuse, match="items.jsonl"):
        compare.run(allow_stub=True, **args)
    # labels not complete: refused before anything else is read
    write_labels(labels, [["V01", "F01", "", ""]])
    with pytest.raises(compare.Refuse, match="not complete"):
        compare.run(allow_stub=True, **dict(args, construction_path="/nonexistent"))


def test_compare_refuses_an_incomplete_judge_run(env):
    paths, items = make_val_env(env)
    d = run_validation.run(paths=paths, stub=True, max_calls=1, out=lambda s: None)
    labels = str(env["tmp"] / "labels.csv")
    write_labels(labels, [[i["id"], "none", "", ""] for i in items])
    live_manifest(paths.scores_root, fixture_prompt_hash(paths))
    with pytest.raises(compare.Refuse, match="incomplete"):
        compare.run(labels, d, paths.items, "/nonexistent", paths.registry, paths.scores_root, allow_stub=True)


def test_live_manifests_keeps_only_the_latest_judgment_per_run(tmp_path):
    root = str(tmp_path)

    def put(folder, run_id, tag, status="complete"):
        d = os.path.join(root, folder)
        os.makedirs(d)
        with open(os.path.join(d, "manifest.json"), "w") as f:
            json.dump({"run_id": run_id, "status": status, "stub": False, "tag": tag, "source_run": {"x": 1}}, f)

    put("RUN_A", "RUN_A", "a1")
    put("RUN_A__2", "RUN_A", "a2")
    put("RUN_B", "RUN_B", "b1")          # a different run, single judgment
    put("RUN_C", "RUN_C", "c1")
    put("RUN_C__2", "RUN_C", "c2", status="incomplete")  # incomplete must not supersede
    put("RUN_D", "RUN_D", "d1")
    put("RUN_D__2", "RUN_D", "d2")
    put("RUN_D__10", "RUN_D", "d10")     # numeric, not lexical, ordering
    got = {m["run_id"]: m["tag"] for m in vlib.live_manifests(root)}
    assert got == {"RUN_A": "a2", "RUN_B": "b1", "RUN_C": "c1", "RUN_D": "d10"}


# ---------------------------------------------------------------- the real judge setup

def test_real_prompt_hash_equals_the_committed_live_runs():
    """Read-only: the validation judge builds the identical prompt prefix to the three committed live runs."""
    paths = run_judge.Paths()
    cfg = yaml.safe_load(open(paths.config))
    pb = PromptBuilder(read_jsonl(paths.registry), open(paths.near_misses).read(),
                       make_labels(read_jsonl(paths.registry), cfg["shuffle_seed"]), open(paths.prompt).read())
    live = vlib.live_manifests(paths.scores_root)
    assert len(live) >= 3
    assert all(m["prompt_hash"] == pb.prefix_hash for m in live)
    assert run_validation.run_id_for(cfg) == "validation_20261019"
