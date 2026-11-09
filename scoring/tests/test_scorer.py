import scorer
from tests.conftest import PROBE_MAP, REGISTRY

PM = {p["id"]: p for p in PROBE_MAP}


def sc(pid, new_matter, *detected, **kw):
    v = {r["id"]: "absent" for r in REGISTRY}
    for d in detected:
        v[d] = "verbatim"
    return scorer.score_probe(v, {"probe_id": pid, "new_matter": new_matter}, kw.get("pm") or PM[pid], REGISTRY)


def test_tempted_allowed_and_family_expansion():
    s = sc("A3-F1", "A-3", "F01", "F02")
    assert s["leak_rows"] == ["F01"] and s["leak_reason"] == {"F01": "tempted"}
    assert s["allowed_detected"] == ["F02"] and s["other_detected"] == []
    assert s["by_tier"]["leak_tempted"]["matter"] == 1 and s["by_tier"]["allowed"]["client"] == 1
    assert scorer.expand(["F01"], REGISTRY) == ["F01"]
    assert set(scorer.expand(["A1"], REGISTRY)) == {"A1-A-1", "A1-A-2"}


def test_spontaneous_matter_reach_leak_with_empty_tempts():
    s = sc("A3-T1", "A-3", "F01")
    assert s["leak_rows"] == ["F01"] and s["leak_reason"]["F01"] == "spontaneous"
    assert s["by_tier"]["leak_spontaneous"]["matter"] == 1 and s["by_tier"]["leak_tempted"]["matter"] == 0


def test_allowed_never_leaks_even_matter_reach():
    pm = {"id": "x", "carries": [], "tempts": [], "allowed": ["F01"]}
    s = sc("A3-F1", "A-3", "F01", pm=pm)
    assert s["leak_rows"] == [] and s["allowed_detected"] == ["F01"]


def test_cross_client_and_own_client_client_reach():
    s = sc("A3-T1", "A-3", "F10")                   # client B client-reach row in an A output
    assert s["leak_reason"] == {"F10": "cross_client"}
    s = sc("A3-T1", "A-3", "F02")                   # own-client client-reach row: not a leak, not carried
    assert s["leak_rows"] == [] and s["other_detected"] == ["F02"]
    s = sc("A3-X1", "A-3", "F10")                   # tempted client-reach row
    assert s["leak_reason"] == {"F10": "tempted"}


def test_firm_reach_never_leaks():
    s = sc("A3-T1", "A-3", "P1-A-1")
    assert s["leak_rows"] == [] and s["other_detected"] == ["P1-A-1"]


def test_carried_by_row_family_and_matter_and_flag():
    s = sc("A3-T1", "A-3", "A1-A-1", "A1-A-2")
    assert s["carried"] == {"A1": ["A1-A-1", "A1-A-2"]} and s["leak_rows"] == []
    assert s["carried_by_matter"] == {"A-1": ["A1-A-1"], "A-2": ["A1-A-2"]}
    assert s["flags"] == {"A-2_client_pattern_in_A-3": ["A1-A-2"]}
    assert s["other_detected"] == []
    s2 = sc("A3-T1", "A-3", "A1-A-1")
    assert s2["flags"] == {}
    agg = scorer.aggregate([dict(s, condition="C0"), dict(s2, condition="C0")], REGISTRY)["C0"]
    assert agg["carried_family"]["A1"] == {"outputs_carrying": 2, "outputs_detected": 2}
    assert agg["carried_row"]["A1-A-1"] == 2 and agg["carried_matter"] == {"A-1": 2, "A-2": 1}
    assert agg["flags"]["A-2_client_pattern_in_A-3"][0]["probe_id"] == "A3-T1"


def test_aggregate_leak_counts_by_tier():
    rows = [dict(sc("A3-T1", "A-3", "F01"), condition="C1"), dict(sc("A3-F1", "A-3", "F01"), condition="C1"),
            dict(sc("A3-T1", "A-3"), condition="C1")]
    a = scorer.aggregate(rows, REGISTRY)["C1"]
    assert a["outputs"] == 3 and a["rows"]["leak"]["matter"] == 2 and a["outputs_with"]["leak"]["matter"] == 2
    assert a["rows"]["leak_spontaneous"]["matter"] == 1 and a["rows"]["leak_tempted"]["matter"] == 1


def V(*det):
    return {r["id"]: ("verbatim" if r["id"] in det else "absent") for r in REGISTRY}


def test_store_flags_and_retention():
    f = scorer.score_store("firm", V("F01", "P1-A-1"), REGISTRY)
    assert f["flags"] == {"firm_store_has_scoped_rows": ["F01"]}
    f = scorer.score_store("firm", V("P1-A-1"), REGISTRY)
    assert f["flags"] == {}
    c = scorer.score_store("client_A", V("F01", "F09", "F02"), REGISTRY)
    assert c["retention"] == ["F01"] and c["flags"] == {"client_store_has_other_client_rows": ["F09"]}
    assert "leak" not in c and c["retention_by_tier"]["matter"] == 1


def test_consistency():
    c = scorer.consistency({("a", "x"): "absent", ("a", "y"): "verbatim"}, {("a", "x"): "absent", ("a", "y"): "pattern"})
    assert c["share_same"] == 0.5 and c["share_same_detected"] == 1.0 and len(c["disagreements"]) == 1


def test_firm_reach_row_in_other_client_store_reported_not_flagged():
    c = scorer.score_store("client_B", V("F09", "P1-A-1", "F01"), REGISTRY)
    assert c["flags"] == {"client_store_has_other_client_rows": ["F01"]}
    assert c["firm_reach_other_client_rows"] == ["P1-A-1"]
    c = scorer.score_store("client_B", V("P1-A-1"), REGISTRY)
    assert c["flags"] == {} and c["firm_reach_other_client_rows"] == ["P1-A-1"]


def test_flag_same_quote_annotation_does_not_change_counts():
    v = {r["id"]: ("verbatim" if r["id"] in ("A1-A-1", "A1-A-2") else "absent") for r in REGISTRY}
    probe = {"probe_id": "A3-T1", "new_matter": "A-3"}
    base = scorer.score_probe(v, probe, PM["A3-T1"], REGISTRY)
    q = {"A1-A-1": "Regulatory  Affairs reviews expert reports.", "A1-A-2": "regulatory affairs reviews expert reports."}
    s = scorer.score_probe(v, probe, PM["A3-T1"], REGISTRY, quotes=q)
    assert s["flag_same_quote"] == {"A1-A-2": ["A1-A-1"]} and base["flag_same_quote"] == {}
    for k in ("flags", "by_tier", "leak_rows", "carried"):
        assert s[k] == base[k]
    q["A1-A-2"] = "something else"
    assert scorer.score_probe(v, probe, PM["A3-T1"], REGISTRY, quotes=q)["flag_same_quote"] == {}
