"""compare.py family mode (v2) on a synthetic fixture. No model calls, no real labels, no real construction data."""
import csv
import json
import os
import sys

import pytest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "validation"))

import compare  # noqa: E402
from judge.util import sha256_bytes  # noqa: E402

REG = [("F01", "verbatim", "matter"), ("F02", "verbatim", "matter"), ("F09", "verbatim", "matter"),
       ("F10", "paraphrase", "client"), ("A1-A-1", "client_pattern", "client"), ("A1-A-2", "client_pattern", "client"),
       ("P1-A-1", "area_pattern", "firm")]
REGISTRY = [{"id": i, "type": t, "intended_reach": r, "text": "x", "detection_keys": []} for i, t, r in REG]
IDS = ["T1", "T2", "T3", "T4", "T5", "T6"]
HASH, OTHER = "a" * 64, "b" * 64

# Alex's units, the judge's detected rows (verdicts), construction (kind, base source, inserted rows)
ALEX = {"T1": ("A1", "A1=pattern"), "T2": ("F01;F02", "F01=verbatim;F02=unsure"), "T3": ("none", ""),
        "T4": ("P1-A-1", "P1-A-1=pattern"), "T5": ("F10", "F10=paraphrase"), "T6": ("F01", "F01=verbatim")}
JUDGE = {"T1": {"A1-A-2": "pattern"},                                 # sibling row: unit matches
         "T2": {"F01": "verbatim"},                                   # misses F02
         "T3": {},
         "T4": {"P1-A-1": "pattern"},
         "T5": {"F10": "verbatim", "F09": "verbatim"},                # strength differs; extra unit F09
         "T6": {"F01": "verbatim"}}
CONS = {"T1": ("client_pattern", "N0", ["A1-A-1"]), "T2": ("multi", "C1", ["F01", "F02"]), "T3": ("none", "N0", []),
        "T4": ("area_pattern", "N0", ["P1-A-1"]), "T5": ("paraphrase", "C2", ["F10"]),
        "T6": ("verbatim", "C0", ["F01", "F09"])}                     # F09 inserted, not labelled by Alex


def wjsonl(path, rows):
    with open(path, "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def write_labels(path, alex=ALEX):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["item_id", "units_present", "strengths", "notes"])
        for i, (u, s) in alex.items():
            w.writerow([i, u, s, ""])


@pytest.fixture
def fx(tmp_path):
    t = tmp_path
    wjsonl(t / "registry.jsonl", REGISTRY)
    (t / "families.json").write_text('{"A1-A-1": "A1", "A1-A-2": "A1"}')
    wjsonl(t / "items.jsonl", [{"id": i, "text": "text %s" % i} for i in IDS])
    write_labels(str(t / "labels_v2.csv"))
    wjsonl(t / "cons.jsonl", [{"id": i, "kind": k, "base": {"condition": c}, "expected": [{"row": r, "strength": "x"} for r in rows]}
                              for i, (k, c, rows) in CONS.items()])
    judge = t / "judge"
    judge.mkdir()
    wjsonl(judge / "judgments.jsonl", [
        {"item_id": i, "rows": [{"registry_id": r, "verdict": v, "quote": "q", "quote_unverified": False}
                                for r, v in JUDGE[i].items()] + [{"registry_id": "F02", "verdict": "absent"}] * (not JUDGE[i])}
        for i in IDS])
    man = {"run_id": compare.V2_RUN_ID, "kind": "validation", "status": "complete", "stub": False, "set": "v2",
           "judge_model": "m", "prompt_hash": HASH, "items_hash": sha256_bytes((t / "items.jsonl").read_bytes())}
    (judge / "manifest.json").write_text(json.dumps(man))
    live = t / "scores" / "LIVE1"
    live.mkdir(parents=True)
    (live / "manifest.json").write_text(json.dumps({"run_id": "LIVE1", "status": "complete", "stub": False,
                                                     "prompt_hash": HASH, "source_run": {"firm": {}}}))
    args = dict(labels_path=str(t / "labels_v2.csv"), judge_dir=str(judge), items_path=str(t / "items.jsonl"),
                construction_path=str(t / "cons.jsonl"), registry_path=str(t / "registry.jsonl"),
                scores_root=str(t / "scores"), families_path=str(t / "families.json"))
    return {"t": t, "judge": judge, "man": man, "args": args}


def set_manifest(fx, **kw):
    fx["man"].update(kw)
    (fx["judge"] / "manifest.json").write_text(json.dumps(fx["man"]))


def test_primary_figure_per_unit_and_splits(fx):
    text, res = compare.run_units(**fx["args"])
    assert res["matches"] == ["T1", "T3", "T4", "T6"] and res["mismatch"] == ["T2", "T5"]
    assert len(res["units"]) == 6 and "A1" in res["units"] and "A1-A-1" not in res["units"]
    assert res["by_unit"]["F02"] == [0, 0, 1, 5] and res["by_unit"]["F09"] == [0, 1, 0, 5]
    assert res["by_unit"]["A1"][:3] == [1, 0, 0]
    assert res["by_tier"]["matter"][:3] == [2, 1, 1]       # F01 x2 TP, F09 FP, F02 FN
    # strength: F01 x2 agree, A1 agree, P1 agree, F10 differs; F02 unsure not counted (and not detected anyway)
    assert res["strength"]["pairs"]["verbatim"] == [2, 2] and res["strength"]["pairs"]["paraphrase"] == [1, 0]
    assert res["strength"]["pairs"]["client_pattern"] == [1, 1] and res["strength"]["pairs"]["area_pattern"] == [1, 1]
    assert res["by_source"] == {"N0": [3, 3], "memory-condition": [1, 3]}
    assert res["by_kind"]["multi"] == [0, 1] and res["by_kind"]["none"] == [1, 1]
    assert res["label_quality"] == {"inserted": 7, "unlabelled": [{"item": "T6", "unit": "F09"}]}
    assert "4 of 6 items match" in text and "NOT MET" in text
    assert "Alex {F01, F02}; judge {F01}" in text and "1 of 7 inserted units not labelled by Alex: T6 F09" in text
    assert "No post-hoc" not in text
    last = text.rstrip("\n").split("\n")[-1]
    assert last.startswith("FAIL") and "item-level agreement 67%" in last


def test_strongest_verdict_per_family_unit():
    j = compare.judge_units({"T": {"A1-A-1": {"verdict": "pattern"}, "A1-A-2": {"verdict": "verbatim"}}},
                            {"A1-A-1": "A1", "A1-A-2": "A1"})
    assert j == {"T": {"A1": "verbatim"}}


def test_pass_line_ends_the_report_and_is_on_primary_only(fx):


    fixed = dict(ALEX, T2=("F01", "F01=verbatim"), T5=("F10;F09", "F10=paraphrase"))
    write_labels(fx["args"]["labels_path"], fixed)
    text, res = compare.run_units(**fx["args"])
    assert len(res["matches"]) == 6 and text.rstrip("\n").split("\n")[-1] == "PASS"
    # strength disagreement and an unlabelled inserted unit do not move the verdict
    assert res["strength"]["pairs"]["paraphrase"] == [1, 0]


def test_tier_missed_entirely_fails_even_above_the_bar(fx):
    # the judge misses P1 in T4 only; Alex has it in T4 only -> firm tier recall 0
    rows = [json.loads(l) for l in open(fx["judge"] / "judgments.jsonl")]
    for r in rows:
        if r["item_id"] == "T4":
            r["rows"] = [{"registry_id": "F01", "verdict": "absent"}]
    wjsonl(fx["judge"] / "judgments.jsonl", rows)
    fixed = dict(ALEX, T2=("F01", ""), T5=("F10;F09", ""), T4=("P1-A-1", ""))
    write_labels(fx["args"]["labels_path"], fixed)
    text, res = compare.run_units(**fx["args"])
    assert len(res["matches"]) == 5 and res["by_tier"]["firm"][0] == 0
    last = text.rstrip("\n").split("\n")[-1]
    assert last.startswith("FAIL") and "reach tier firm missed entirely" in last and "fact type area_pattern" in last


def test_pre_rejudge_notice(fx):
    set_manifest(fx, prompt_hash=OTHER)
    with pytest.raises(compare.Refuse, match="prompt_hash"):
        compare.run_units(**fx["args"])
    text, _ = compare.run_units(pre_rejudge=True, **fx["args"])
    assert "PRE-REJUDGE" in text and "not yet usable as a result" in text


def test_checks_come_before_construction_is_read(fx):
    a = dict(fx["args"], construction_path="/nonexistent/labels.jsonl")
    with pytest.raises(compare.Refuse, match="do not cover"):   # sanity: everything else passes, then it is read
        compare.run_units(**a)
    write_labels(a["labels_path"], {i: v for i, v in ALEX.items() if i != "T3"})
    with pytest.raises(compare.Refuse, match="not complete"):
        compare.run_units(**a)
    write_labels(a["labels_path"])
    for kw, msg in ((dict(stub=True), "stub run"), (dict(status="incomplete"), "incomplete"),
                    (dict(set="v1"), "not the v2 validation run"), (dict(run_id="validation_20261019"), "not the v2"),
                    (dict(items_hash="0" * 64), "items.jsonl"), (dict(kind="x"), "not a validation run")):
        set_manifest(fx, **kw)
        with pytest.raises(compare.Refuse, match=msg):
            compare.run_units(**a)
        set_manifest(fx, stub=False, status="complete", set="v2", run_id=compare.V2_RUN_ID,
                     items_hash=sha256_bytes((fx["t"] / "items.jsonl").read_bytes()), kind="validation")
    text, _ = compare.run_units(allow_stub=True, **fx["args"])
    assert "4 of 6" in text


@pytest.mark.parametrize("units,strengths,msg", [
    ("", "", "not complete"), ("ZZ", "", "malformed"), ("F01;F01", "", "malformed"),
    ("F01", "F01=loud", "bad strength"), ("F01", "F02=verbatim", "bad strength"), ("A1-A-1", "", "malformed")])
def test_label_file_refusals(fx, units, strengths, msg):
    write_labels(fx["args"]["labels_path"], dict(ALEX, T1=(units, strengths)))
    with pytest.raises(compare.Refuse, match=msg):
        compare.run_units(**fx["args"])


def test_unknown_item_in_labels_refused(fx):
    write_labels(fx["args"]["labels_path"], dict(ALEX, T9=("none", "")))
    with pytest.raises(compare.Refuse, match="unknown items"):
        compare.run_units(**fx["args"])


def test_cli_flags_go_together_and_reject_adjudication(fx):
    with pytest.raises(SystemExit):
        compare.main(["--family-labels", "x.csv"])
    with pytest.raises(SystemExit):
        compare.main(["--set", "v2"])
    with pytest.raises(SystemExit):
        compare.main(["--set", "v2", "--family-labels", "x.csv", "--adjudication", "a.md"])
