import json
import os

import pytest

import run_judge
from judge import firmexport
from judge.stub import StubBackend, default_responder
from judge.util import read_json, read_jsonl


def go(env, **kw):
    kw.setdefault("stub", True)
    return run_judge.run_many([env["run"]], paths=env["paths"], out=lambda s: None, **kw)


def test_full_stub_run_outputs_and_blindness_of_calls(env):
    (d,) = go(env, repeat=True)
    for f in ("blind_map.json", "judgments.jsonl", "lexical.jsonl", "disagreements.jsonl", "candidates.jsonl",
              "candidates_rejected.jsonl", "scores.jsonl", "store_scores.jsonl", "usage.jsonl", "manifest.json",
              "report.md", "repeat_subset.json", "row_scores.jsonl", "lexical_fate.jsonl", "consistency.json"):
        assert os.path.exists(os.path.join(d, f)), f
    m = read_json(os.path.join(d, "manifest.json"))
    assert m["status"] == "complete" and m["stub"] and m["rejected_calls"] == 0
    for k in ("judge_model", "prompt_hash", "registry_hash", "scoring_git", "dropped_unknown_keys"):
        assert k in m
    scores = {s["probe_id"]: s for s in read_jsonl(os.path.join(d, "scores.jsonl"))}
    assert len(scores) == 3
    assert scores["A3-F1"]["leak_reason"] == {"F01": "tempted"} and scores["A3-F1"]["allowed_detected"] == ["F02"]
    assert scores["A3-X1"]["leak_reason"] == {"F09": "tempted"}
    assert scores["A3-T1"]["carried"]["A1"] == ["A1-A-1"] and scores["A3-T1"]["leak_rows"] == []
    stores = {s["store"]: s for s in read_jsonl(os.path.join(d, "store_scores.jsonl"))}
    assert stores["client_A"]["retention"] == ["F01"]
    assert stores["firm"]["flags"] == {"firm_store_has_scoped_rows": ["F02"]}
    cands = read_jsonl(os.path.join(d, "candidates.jsonl"))
    assert len(cands) == 1 and cands[0]["output_quote"] == "STUBCAND" and cands[0]["untraced"]
    fate = {(f["store"], f["registry_id"]): f["lexical_hit"] for f in read_jsonl(os.path.join(d, "lexical_fate.jsonl"))}
    assert fate[("matter_only", "F09")] is True
    cons = read_json(os.path.join(d, "consistency.json"))
    assert cons["rows"] == 7 and cons["share_same"] == 1.0
    rep = open(os.path.join(d, "report.md")).read()
    assert "Alex's mark" in rep and "Spontaneous leaks" in rep and "Tempted leaks" in rep and "STUB RUN" in rep
    assert any(it.endswith("_r2") for it in read_json(os.path.join(d, "blind_map.json"))["calls"])
    ids = list(read_json(os.path.join(d, "blind_map.json"))["calls"])
    assert all(len(i.split("_")[0]) == 16 for i in ids)


def test_blind_map_written_before_first_call(env):
    seen = []

    class Spy(StubBackend):
        def complete(self, prompt):
            seen.append(os.path.exists(os.path.join(env["paths"].scores_root, "RUN1_C0", "blind_map.json")))
            return super().complete(prompt)

    go(env, backend=Spy())
    assert seen and all(seen)


def test_never_overwrite_and_resume(env):
    d1, = go(env, max_calls=2)
    assert read_json(os.path.join(d1, "manifest.json"))["status"] == "incomplete"
    with pytest.raises(SystemExit):
        go(env)                                         # incomplete, no --resume
    d1b, = go(env, resume=True)
    assert d1b == d1 and read_json(os.path.join(d1, "manifest.json"))["status"] == "complete"
    d2, = go(env)                                       # complete: new folder, never overwritten
    assert d2 == d1 + "__2" and os.path.isdir(d1)


def test_rejected_calls_counted_in_manifest(env):
    n = {"i": 0}

    def responder(p):
        n["i"] += 1
        return "garbage" if n["i"] == 1 else default_responder(p)

    d, = go(env, backend=StubBackend(responder))
    m = read_json(os.path.join(d, "manifest.json"))
    assert m["rejected_calls"] == 1 and m["status"] == "incomplete" and len(m["missing_calls"]) == 1
    assert [f for f in os.listdir(os.path.join(d, "calls")) if ".rejected" in f]


def test_unknown_keys_counted_in_manifest(env):
    def responder(p):
        o = json.loads(default_responder(p))
        o["note"] = "x"
        return json.dumps(o)

    d, = go(env, backend=StubBackend(responder))
    assert read_json(os.path.join(d, "manifest.json"))["dropped_unknown_keys"] == 7


def test_combined_report_and_no_overwrite(env):
    d, = go(env)
    p = run_judge.combine([d], env["paths"], "x1")
    assert os.path.exists(p)
    with pytest.raises(SystemExit):
        run_judge.combine([d], env["paths"], "x1")


def test_live_run_needs_typed_yes_and_guards(env):
    with pytest.raises(SystemExit):
        run_judge.run_many([env["run"]], paths=env["paths"], stub=False, environ={"ANTHROPIC_API_KEY": "k"}, out=lambda s: None)
    with pytest.raises(SystemExit):                     # not a git repo -> guard fails
        run_judge.run_many([env["run"]], paths=env["paths"], stub=False, environ={}, out=lambda s: None)


def test_firm_hash_matches_real_run_manifest():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    firm = os.path.join(here, "..", "pipeline", "data", "firm")
    run = os.path.join(here, "..", "pipeline", "runs", "20261019T232425Z_C0", "manifest.json")
    if not (os.path.isdir(firm) and os.path.exists(run)):
        pytest.skip("pipeline run folder not present")
    m = read_json(run)
    problems, info = firmexport.check_against_manifest(firm, os.path.join(firm, "..", "FIRM_TAG"), m)
    assert problems == [], problems


def test_store_candidates_kept_apart_from_probe_candidates(env):
    store = os.path.join(env["run"], "stores", "client_A.jsonl")
    with open(store, "w") as f:
        f.write(json.dumps({"text": "Larkspur review noted. STUBCAND"}) + "\n")
    (d,) = go(env)
    cands = read_jsonl(os.path.join(d, "candidates.jsonl"))
    assert [c["kind"] for c in cands] == ["probe"]
    sc = read_jsonl(os.path.join(d, "store_candidates.jsonl"))
    assert [c["tap"] for c in sc] == ["store:client_A"] and sc[0]["output_quote"] == "STUBCAND"
    counts = read_json(os.path.join(d, "manifest.json"))["counts"]
    assert counts["candidates"] == 1 and counts["store_candidates"] == 1 and counts["candidates_untraced"] == 1
