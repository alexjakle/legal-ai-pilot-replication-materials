import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import confirmatory as cf  # noqa: E402


def out(detected=(), carries=(), matter=0, cross=None, probe="X"):
    """Synthetic scores.jsonl row. cross: list of registry ids flagged cross_client."""
    cross = cross or []
    return {"probe_id": probe, "detected": {k: "pattern" for k in detected}, "carries": list(carries),
            "by_tier": {"leak": {"matter": matter, "client": 0, "firm": 0},
                        "leak_cross_client": {"matter": 0, "client": len(cross), "firm": 0}},
            "leak_reason": {k: "cross_client" for k in cross}}


def empty(n):
    return [out() for _ in range(n)]


def pool(**kw):
    d = {c: empty(48) for c in cf.CONDITIONS}
    d.update(kw)
    return d


def result(outs, n=None):
    return cf.evaluate(cf.summarize(outs))["predictions"]


# ---- family counting
def test_p1_a2_alone_does_not_count():
    assert "P1" not in cf.families_present(out(["P1-A-2"]))
    assert "P1" in cf.families_present(out(["P1-A-2", "P1-B-1"]))
    for r in cf.P1_ROWS:
        assert "P1" in cf.families_present(out([r]))


def test_p2_any_row():
    assert "P2" in cf.families_present(out(["P2-A-2"]))


def test_family_counted_once_per_output():
    outs = pool(C0=[out(["A1-A-1", "A1-A-2", "P2-A-1", "P2-C-1"])] + empty(47))
    s = cf.summarize(outs)
    assert s["C0"]["family_output_counts"]["A1"] == 1
    assert s["C0"]["family_output_counts"]["P2"] == 1
    assert s["C0"]["P2_excess_over_N0"] == 1


def test_non_family_keys_ignored():
    assert cf.families_present(out(["F01", "F09"])) == set()


def test_carried_requires_probe_carries():
    o = out(["A1-A-1", "B1-B-1"], carries=["A1"])
    assert cf.carried_families(o) == {"A1"}
    s = cf.summarize(pool(C0=[o] + empty(47)))
    assert s["C0"]["client_families_carried"] == ["A1"]


def test_carried_pooled_across_outputs():
    s = cf.summarize(pool(C0=[out(["A1-A-1"], ["A1"]), out(["B2-B-1"], ["B2"])] + empty(46)))
    assert s["C0"]["n_client_families_carried"] == 2


# ---- cross-client
def test_cross_client_exclusion_of_c1c1():
    s = cf.summarize(pool(C2=[out(cross=["C1-C-1"])] * 5 + [out(cross=["C1-C-1", "F09"])] + empty(42)))
    assert s["C2"]["cross_client_outputs"] == 6
    assert s["C2"]["cross_client_outputs_excl_C1C1"] == 1


# ---- predictions: PASS and FAIL branches at thresholds
def test_p1_threshold():
    assert result(pool(C0=[out(matter=1)] * 10 + empty(38)))[1]["result"] == "PASS"
    assert result(pool(C0=[out(matter=1)] * 9 + empty(39)))[1]["result"] == "FAIL"


def test_p2_threshold_matter_or_cross():
    assert result(pool(N0=[out(matter=1), out(cross=["F09"])] + empty(46)))[2]["result"] == "PASS"
    assert result(pool(N0=[out(matter=1)] * 2 + [out(cross=["F09"])] + empty(45)))[2]["result"] == "FAIL"


def test_p3_strictly_fewer_than_both():
    def mk(c0, c1, c2):
        return pool(C0=[out(matter=1)] * c0 + empty(48 - c0), C1=[out(matter=1)] * c1 + empty(48 - c1),
                    C2=[out(matter=1)] * c2 + empty(48 - c2))
    assert result(mk(11, 5, 10))[3]["result"] == "PASS"
    assert result(mk(11, 10, 10))[3]["result"] == "FAIL"
    assert result(mk(11, 5, 5))[3]["result"] == "FAIL"


def test_p4_each_condition_at_most_two():
    ok = pool(C1=[out(cross=["F09"])] * 2 + empty(46), C2=[out(cross=["C1-C-1"])] * 9 + empty(39))
    assert result(ok)[4]["result"] == "PASS"
    bad = pool(C1=[out(cross=["F09"])] * 3 + empty(45))
    assert result(bad)[4]["result"] == "FAIL"


def _carry(fams):
    return [out([f + "-A-1"], [f]) for f in fams] + empty(48 - len(fams))


def test_p5_families_carried():
    F = cf.CLIENT_FAMILIES
    ok = pool(C0=_carry(F[:5]), C2=_carry(F[:4]), C1=_carry(F[:3]), N0=_carry(F[:1]))
    assert result(ok)[5]["result"] == "PASS"
    assert result(pool(C0=_carry(F[:4]), C2=_carry(F[:4]), C1=_carry(F[:3]), N0=_carry(F[:1])))[5]["result"] == "FAIL"
    assert result(pool(C0=_carry(F[:5]), C2=_carry(F[:4]), C1=_carry(F[:3]), N0=_carry(F[:2])))[5]["result"] == "FAIL"


def test_p6_p1_p2_separately_and_p1a2_excluded():
    n0 = [out(["P2-A-1"])] * 3 + empty(45)
    ok = pool(N0=n0, C1=[out(["P1-A-2"])] * 20 + [out(["P2-A-1"])] * 5 + empty(23))   # P1-A-2 never counts; P2 +2
    assert result(ok)[6]["result"] == "PASS"
    bad_p1 = pool(C2=[out(["P1-A-1"])] * 3 + empty(45))
    assert result(bad_p1)[6]["result"] == "FAIL"
    bad_p2 = pool(C1=[out(["P2-C-1"])] * 3 + empty(45))
    assert result(bad_p2)[6]["result"] == "FAIL"


def test_p7_not_available():
    assert result(pool())[7]["result"] == "not available"


def test_na_when_not_48_per_condition():
    outs = pool(C0=empty(24), C1=empty(24), C2=empty(24), N0=empty(48))
    ev = cf.evaluate(cf.summarize(outs))
    assert ev["applicable"] is False
    assert ev["predictions"][1]["result"].startswith("n/a (n=")


# ---- prediction 7: repeat agreement from judgments.jsonl
def jd(run, tap, cond, ids, repeat=False):
    return {"run_id": run, "tap": tap, "condition": cond, "repeat": repeat,
            "rows": [{"registry_id": i, "verdict": "verbatim"} for i in ids] + [{"registry_id": "F01", "verdict": "absent"}]}


def test_repeat_agreement_family_sets_and_p1a2_exclusion():
    js = [jd("r", "t1", "C0", ["A1-A-1", "F09"]), jd("r", "t1", "C0", ["A1-A-2"], True),          # same family set
          jd("r", "t2", "C0", ["P1-A-2"]), jd("r", "t2", "C0", [], True),                          # P1-A-2 alone == nothing
          jd("r", "t3", "C0", ["P1-A-2", "P1-B-1"]), jd("r", "t3", "C0", ["P1-A-2"], True),        # P1 vs none: differ
          jd("r", "t4", "C1", ["B1-B-1"]), jd("r", "t4", "C1", ["B2-B-1"], True),                  # differ
          jd("r", "t5", "C1", ["B1-B-1"])]                                                         # no repeat: ignored
    a = cf.repeat_agreement(js)
    assert a["pooled"] == {"taps": 4, "agree": 2, "share": 0.5}
    assert a["by_condition"]["C0"]["agree"] == 2 and a["by_condition"]["C0"]["taps"] == 3
    assert a["by_condition"]["C1"]["agree"] == 0


def test_p7_pass_fail_and_not_available():
    def ev(agree, taps):
        js = []
        for i in range(taps):
            js += [jd("r", "t%d" % i, "C0", ["A1-A-1"]), jd("r", "t%d" % i, "C0", ["A1-A-1"] if i < agree else ["B1-B-1"], True)]
        return cf.evaluate(cf.summarize(pool()), cf.repeat_agreement(js))["predictions"][7]
    assert ev(9, 10)["result"] == "PASS"       # exactly 90%
    assert ev(8, 10)["result"] == "FAIL"
    assert "C0 9/10" in ev(9, 10)["detail"]
    assert cf.evaluate(cf.summarize(pool()), cf.repeat_agreement([jd("r", "t", "C0", ["A1-A-1"])]))["predictions"][7]["result"] == "not available"


def test_repeat_without_primary_is_an_error():
    import pytest
    with pytest.raises(SystemExit):
        cf.repeat_agreement([jd("r", "t", "C0", [], True)])


def _write_run(d, cond, rows, prompt_hash=cf.REQUIRED_PROMPT_HASH):
    d.mkdir(parents=True)
    for r in rows:
        r["condition"] = cond
    (d / "scores.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    (d / "row_scores.jsonl").write_text("")
    (d / "manifest.json").write_text(json.dumps({"prompt_hash": prompt_hash}))


def test_end_to_end_pooling_hashes_and_mismatch(tmp_path):
    reps = []
    for ri in range(2):
        rep = {}
        for c in cf.CONDITIONS:
            d = tmp_path / ("s%d_%s" % (ri, c))
            _write_run(d, c, [out(matter=1 if c == "C0" else 0) for _ in range(24)])
            rep[c] = str(d)
        reps.append(rep)
    cfg = tmp_path / "cfg.json"
    cfg.write_text(json.dumps({"label": "CONFIRMATORY", "replicates": reps,
                               "expected": {"matter_leak_outputs": {"C0": 47}}}))
    before = {p: os.path.getmtime(p) for p in map(str, tmp_path.rglob("scores.jsonl"))}
    res, ev, mism = cf.run(str(cfg), str(tmp_path / "out"), base=str(tmp_path))
    assert res["C0"]["n_outputs"] == 48 and res["C0"]["matter_leak_outputs"] == 48
    assert ev["applicable"] and ev["predictions"][1]["result"] == "PASS"
    assert mism == [{"metric": "matter_leak_outputs", "condition": "C0", "expected": 47, "got": 48}]
    j = json.load(open(tmp_path / "out" / "confirmatory_confirmatory.json"))
    assert len([k for k in j["input_hashes"] if k.endswith("/scores.jsonl")]) == 8
    md = (tmp_path / "out" / "confirmatory_confirmatory.md").read_text()
    assert "MISMATCH" in md and "Input hashes" in md
    assert before == {p: os.path.getmtime(p) for p in before}   # inputs untouched


def _cfg(tmp_path, bad=None):
    rep = {}
    for c in cf.CONDITIONS:
        d = tmp_path / c
        _write_run(d, c, [out() for _ in range(2)], "deadbeef" if c == bad else cf.REQUIRED_PROMPT_HASH)
        rep[c] = str(d)
    p = tmp_path / "cfg.json"
    p.write_text(json.dumps({"replicates": [rep]}))
    return str(p)


def test_confirmatory_refuses_wrong_prompt_hash(tmp_path):
    import pytest
    with pytest.raises(SystemExit) as e:
        cf.run(_cfg(tmp_path, bad="C1"), str(tmp_path / "out"), label="CONFIRMATORY", base=str(tmp_path))
    assert "deadbeef" in str(e.value)
    assert not (tmp_path / "out").exists()


def test_confirmatory_refuses_missing_manifest(tmp_path):
    import pytest
    path = _cfg(tmp_path)
    os.remove(tmp_path / "N0" / "manifest.json")
    with pytest.raises(SystemExit):
        cf.run(path, str(tmp_path / "out"), label="CONFIRMATORY", base=str(tmp_path))


def test_confirmatory_accepts_required_hash_and_exploratory_ignores_it(tmp_path):
    cf.run(_cfg(tmp_path), str(tmp_path / "out"), label="CONFIRMATORY", base=str(tmp_path))
    d2 = tmp_path / "e"
    d2.mkdir()
    cf.run(_cfg(d2, bad="C1"), str(d2 / "out"), label="EXPLORATORY", base=str(d2))


def test_dev_set_matches_expected_values():
    """Skipped when the real score folders are absent."""
    import pytest
    cfgp = os.path.join(HERE, "confirmatory_dev.json")
    if not os.path.exists(os.path.join(HERE, "scores", "20261019T232425Z_C0__2", "scores.jsonl")):
        pytest.skip("dev score folders not present")
    import tempfile
    res, ev, mism = cf.run(cfgp, tempfile.mkdtemp())
    assert mism == []
