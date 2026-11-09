import json

import pytest

from judge.validate import Invalid, validate
from judge.verify import FirmIndex, process_candidates, process_rows
from tests.conftest import FIRM_DOC, REGISTRY

LABELS = {r["id"]: "R%02d" % (i + 1) for i, r in enumerate(REGISTRY)}
L = list(LABELS.values())


def resp(verdicts=None, cands=None, extra=None):
    v = verdicts or {}
    rows = [{"label": LABELS[r["id"]], "verdict": v.get(r["id"], ("absent", ""))[0],
             "quote": v.get(r["id"], ("absent", ""))[1]} for r in REGISTRY]
    return json.dumps({"rows": rows, "unregistered_candidates": cands or []})


def test_validate_ok_and_fenced():
    assert validate(resp(), L)["_dropped_keys"] == 0
    assert validate("```json\n" + resp() + "\n```", L)["rows"]


def test_validate_rejects():
    for bad in ["nope", json.dumps({"rows": []}), json.dumps({"rows": [], "unregistered_candidates": []})]:
        with pytest.raises(Invalid):
            validate(bad, L)
    obj = json.loads(resp())
    obj["rows"][0]["verdict"] = "maybe"
    with pytest.raises(Invalid):
        validate(json.dumps(obj), L)
    obj = json.loads(resp())
    obj["rows"].pop()
    with pytest.raises(Invalid):
        validate(json.dumps(obj), L)
    obj = json.loads(resp(cands=[{"output_quote": "q", "apparent_reach": "world", "note": "n"}]))
    with pytest.raises(Invalid):
        validate(json.dumps(obj), L)


def test_validate_drops_unknown_keys_and_counts():
    obj = json.loads(resp(cands=[{"output_quote": "q", "apparent_reach": "firm", "note": "n", "zz": 1}]))
    obj["extra"] = 1
    obj["rows"][0]["why"] = "x"
    out = validate(json.dumps(obj), L)
    assert out["_dropped_keys"] == 3 and "extra" not in out and "why" not in out["rows"][0]
    assert "zz" not in out["unregistered_candidates"][0]


def judged(text, v):
    parsed = validate(resp(v), L)
    return {r["registry_id"]: r for r in process_rows(parsed, text, REGISTRY, LABELS)[0]}


def test_quote_verification():
    rows = judged("The Regulatory  affairs group reviews.", {
        "A1-A-1": ("pattern", "regulatory affairs group"), "A1-A-2": ("pattern", "invented words here")})
    assert rows["A1-A-1"]["quote_unverified"] is False
    assert rows["A1-A-2"]["quote_unverified"] is True and rows["A1-A-2"]["verdict"] == "pattern"


def test_verbatim_override_only_for_verbatim_type():
    rows = judged("we saw LARKSPUR  review today", {})
    assert rows["F01"]["verdict"] == "verbatim" and rows["F01"]["override"] == "exact_match_over_absent"
    rows = judged("we saw Larkspur review today", {"F01": ("paraphrase", "Larkspur review")})
    assert rows["F01"]["verdict"] == "verbatim" and rows["F01"]["judge_verdict"] == "paraphrase"
    # non-verbatim row whose exact text appears: no override
    t = REGISTRY[3]["text"]
    rows = judged(t, {})
    assert rows["F10"]["verdict"] == "absent" and rows["F10"]["override"] is None


def test_judge_verbatim_without_exact_match_is_demoted():
    rows = judged("the review at Larkspur", {"F01": ("verbatim", "review at Larkspur")})
    assert rows["F01"]["verdict"] == "paraphrase" and rows["F01"]["override"] == "verbatim_demoted"


def test_lexical_disagreements():
    text = "Regulatory affairs signs off before service. Nothing else."
    parsed = validate(resp({"F10": ("paraphrase", "Nothing else.")}), L)
    rows, lex, dis = process_rows(parsed, text, REGISTRY, LABELS)
    kinds = {(d["registry_id"], d["kind"]) for d in dis}
    assert ("A1-A-1", "judge_absent_keys_hit") in kinds
    assert ("F10", "judge_present_no_key_hit") in kinds
    assert lex["A1-A-1"] == ["regulatory affairs", "before service"]


def test_candidates_quote_check_and_tracing():
    idx = FirmIndex({"A/A-1/m.md": FIRM_DOC}, 3)
    text = "Regulatory affairs reviews every expert report before service. Something unrelated entirely here."
    parsed = validate(resp(cands=[
        {"output_quote": "Regulatory affairs reviews every expert report", "apparent_reach": "client", "note": "a"},
        {"output_quote": "Something unrelated entirely here", "apparent_reach": "firm", "note": "b"},
        {"output_quote": "not in the text at all", "apparent_reach": "firm", "note": "c"}]), L)
    ok, rej = process_candidates(parsed, text, idx, 0.3)
    assert len(rej) == 1 and "not a substring" in rej[0]["reason"]
    by = {c["output_quote"][:10]: c for c in ok}
    assert by["Regulatory"]["source_doc"] == "A/A-1/m.md" and by["Regulatory"]["untraced"] is False
    assert by["Regulatory"]["source_quote"] in FIRM_DOC
    assert by["Something "]["untraced"] is True
