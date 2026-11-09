import json
import subprocess
from pathlib import Path

import pytest

from src import cli, stages
from src.config import Config, ROOT, sha256_text
from src.llm import (ApiKeyPresent, CallBudget, ClaudeCliBackend, LLM, LLMError, MaxCallsExceeded,
                     PromptMismatch, TransientError, parse_result, usage_row)
from src.runfs import read_json, read_jsonl
from src.stores import exclude_walled, load_store, render_items, verify_patterns

SAMPLE = json.dumps({
    "type": "result", "is_error": False, "result": "ok", "session_id": "sess-1",
    "total_cost_usd": 0.0123, "duration_ms": 4321,
    "usage": {"input_tokens": 3, "output_tokens": 5, "cache_creation_input_tokens": 24000,
              "cache_read_input_tokens": 100},
    "modelUsage": {"claude-sonnet-5-5": {"inputTokens": 3}},
})


@pytest.fixture
def cfg(tmp_path):
    return Config(ROOT, runs_root=tmp_path / "runs")


# 1. store loader and wall exclusion
def test_store_loader_and_wall_exclusion(tmp_path):
    from src.runfs import write_jsonl
    p = tmp_path / "s.jsonl"
    rows = [{"artifact_id": "x1", "eligibility_tags": ["wall:A-3"], "text": "walled"},
            {"artifact_id": "x2", "eligibility_tags": [], "text": "open"},
            {"artifact_id": "x3", "text": "no tags key"}]
    write_jsonl(p, rows)
    loaded = load_store(p)
    assert len(loaded) == 3
    assert [r["artifact_id"] for r in exclude_walled(loaded, "A-3")] == ["x2", "x3"]
    assert len(exclude_walled(loaded, "B-2")) == 3
    assert render_items(exclude_walled(loaded, "A-3")) == "- open\n- no tags key"
    assert load_store(tmp_path / "missing.jsonl") == []


# 2. command the claude_cli backend would build
def test_command_levels():
    b = ClaudeCliBackend("claude-sonnet-5-5", system_prompt="SP")
    base = ["claude", "-p", "--output-format", "json", "--model", "claude-sonnet-5-5"]
    assert b.build_command(overhead="L0") == base + ["--no-session-persistence"]
    assert b.build_command(overhead="L1") == base + ["--tools", "", "--no-session-persistence"]
    l2 = b.build_command(overhead="L2")
    assert l2 == base + ["--tools", "", "--system-prompt", "SP", "--disable-slash-commands",
                         "--strict-mcp-config", "--setting-sources", "", "--no-session-persistence"]
    assert b.build_command(session_id="abc", overhead="L1") == base + ["--tools", "", "--resume", "abc"]
    assert b.build_command(stateful=True, overhead="L0") == base
    for lvl in ("L0", "L1", "L2"):
        assert "--bare" not in b.build_command(overhead=lvl)


def test_backend_runs_outside_repo_with_prompt_on_stdin():
    seen = {}

    def runner(cmd, **kw):
        seen.update(kw, cmd=cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout=SAMPLE, stderr="")

    b = ClaudeCliBackend("m", runner=runner, environ={})
    out = b.complete("PROMPT", None, False, "L0", "s", "r")
    assert seen["input"] == "PROMPT"
    assert not str(seen["cwd"]).startswith(str(ROOT))
    assert out["text"] == "ok" and out["session_id"] == "sess-1"


# 3. sample JSON -> usage line
def test_parse_sample_to_usage_line():
    parsed = parse_result(SAMPLE)
    row = usage_row("run1", "notes", "C1", "notes", "claude-sonnet-5-5", parsed, 0, 999, "T")
    assert row == {
        "run_id": "run1", "timestamp": "T", "stage": "notes", "condition": "C1", "role": "notes",
        "model": "claude-sonnet-5-5", "session_id": "sess-1", "input_tokens": 3, "output_tokens": 5,
        "cache_write_tokens": 24000, "cache_read_tokens": 100, "total_cost_usd": 0.0123,
        "latency_ms": 4321, "exit_status": 0}


def test_error_result_raises():
    bad = json.dumps({"type": "result", "is_error": True, "result": "boom"})
    with pytest.raises(LLMError):
        parse_result(bad)
    with pytest.raises(TransientError):
        parse_result(json.dumps({"is_error": True, "result": "API overloaded"}))


# 4. refuse when ANTHROPIC_API_KEY is set
def test_refuses_with_api_key(cfg, tmp_path):
    with pytest.raises(ApiKeyPresent):
        ClaudeCliBackend("m", environ={"ANTHROPIC_API_KEY": "x"}).complete("p", None, False, "L0", "s", "r")
    with pytest.raises(ApiKeyPresent):
        LLM(cfg, tmp_path, "r", "C1", live=True, environ={"ANTHROPIC_API_KEY": ""})


# 5. skip-if-exists with prompt hash; budget
def test_skip_and_prompt_mismatch(cfg, tmp_path):
    llm = LLM(cfg, tmp_path, "r", "C1")
    a = llm.call("downstream", "downstream", "c1", "hello")
    assert not a.skipped
    b = llm.call("downstream", "downstream", "c1", "hello")
    assert b.skipped and b.text == a.text
    assert len(read_jsonl(tmp_path / "usage.jsonl")) == 1
    with pytest.raises(PromptMismatch):
        llm.call("downstream", "downstream", "c1", "changed")


def test_max_calls_aborts(cfg, tmp_path):
    llm = LLM(cfg, tmp_path, "r", "C1", budget=CallBudget(1))
    llm.call("downstream", "downstream", "a", "x")
    with pytest.raises(MaxCallsExceeded):
        llm.call("downstream", "downstream", "b", "y")
    assert not (tmp_path / "calls" / "b.json").exists()


def test_one_logged_retry_on_transient(cfg, tmp_path):
    n = {"c": 0}

    def runner(cmd, **kw):
        n["c"] += 1
        if n["c"] == 1:
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="503 overloaded")
        return subprocess.CompletedProcess(cmd, 0, stdout=SAMPLE, stderr="")

    llm = LLM(cfg, tmp_path, "r", "C1", live=True, runner=runner, sleep=lambda s: None, environ={})
    llm.call("downstream", "downstream", "t", "p")
    rows = read_jsonl(tmp_path / "usage.jsonl")
    assert n["c"] == 2 and [r["exit_status"] for r in rows] == ["transient_error:retrying", 0]


def test_codex_stub_raises(cfg, tmp_path):
    from src.llm import CodexCliBackend
    with pytest.raises(NotImplementedError, match="codex_cli"):
        CodexCliBackend().complete("p")


# 6. k=2
def test_k_verification():
    ic = {"a": "X", "b": "X", "c": "Y"}
    kept, dropped = verify_patterns(
        [{"text": "one client", "contributing_items": ["a", "b"]},
         {"text": "two clients", "contributing_items": ["a", "c", "zzz"]}], ic, 2)
    assert [p["text"] for p in kept] == ["two clients"]
    assert kept[0]["contributing_items"] == ["a", "c"]
    assert [p["text"] for p in dropped] == ["one client"]


# 7. end to end on the stub
def _run(cfg, argv):
    assert cli.main(argv, cfg=cfg) == 0


def test_end_to_end_stub_c1_c2_c0(cfg):
    _run(cfg, ["notes"])
    notes_dir = next(cfg.runs_root.glob("notes_*"))
    rows = read_jsonl(notes_dir / "notes.jsonl")
    assert len(rows) == 12 and not any("A-1" in r["id"] for r in rows)
    for cond in ("C0", "C1", "C2"):
        _run(cfg, ["run", "--condition", cond, "--notes", str(notes_dir)])
    runs = {p.name.split("_")[1]: p for p in cfg.runs_root.glob("2*_C*")}
    for cond, d in runs.items():
        assert len(read_jsonl(d / "probe_outputs.jsonl")) == 24
        assert (d / "manifest.json").exists() and (d / "config" / "walls.yaml").exists()
        for r in load_store(d / "stores" / "firm.jsonl") + load_store(d / "stores" / "client_A.jsonl"):
            assert "source_matter" not in r and "matter" not in r
    # C1: the A-2 item tagged wall:A-3 is in client A's store but excluded for A-3
    a = load_store(runs["C1"] / "stores" / "client_A.jsonl")
    assert any("wall:A-3" in r["eligibility_tags"] for r in a)
    prompt = (runs["C1"] / "calls" / "down_A3-T1.prompt.txt").read_text()
    walled = [r for r in a if "wall:A-3" in r["eligibility_tags"]][0]
    assert "- " + walled["text"] not in prompt or sum(1 for r in a if r["text"] == walled["text"]) > 1
    assert len(exclude_walled(a, "A-3")) == len(a) - 1
    # ledger carries source matter; firm item lists its source matters
    led = read_jsonl(runs["C1"] / "ledger.jsonl")
    assert {"A-1", "A-2", "B-1", "C-1"} <= {r["source_matter"] for r in led}
    assert any(r["gate"] == "abstraction_gate" for r in led)
    assert set(led[0]) == {"artifact_id", "source_matter", "gate", "condition", "timestamp"}
    # C2 resumes one session across the five gate calls; C1 does not
    c2 = [read_json(runs["C2"] / "calls" / ("scope_%s.json" % m)) for m in cfg.source_matters]
    assert c2[0]["session_id_in"] is None and all(c["session_id"] for c in c2)
    assert c2[1]["session_id_in"] == c2[0]["session_id"]
    ab = read_json(runs["C2"] / "calls" / "abstraction.json")
    assert ab["session_id_in"] == c2[-1]["session_id"]
    assert read_json(runs["C1"] / "calls" / "abstraction.json")["session_id_in"] is None
    # C0 is the unfiltered baseline
    assert len(load_store(runs["C0"] / "stores" / "firm.jsonl")) == 12
    # resume skips everything
    before = len(read_jsonl(runs["C1"] / "usage.jsonl"))
    _run(cfg, ["run", "--condition", "C1", "--run", str(runs["C1"])])
    assert len(read_jsonl(runs["C1"] / "usage.jsonl")) == before


def test_live_refuses_without_commit_or_with_key(cfg, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    assert cli.main(["notes", "--live"], cfg=cfg) == 1
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    monkeypatch.setattr(cli, "require_clean_git", lambda root: (_ for _ in ()).throw(
        cli.ManifestError("dirty")))
    assert cli.main(["notes", "--live"], cfg=cfg) == 1
    assert not list(cfg.runs_root.glob("*"))


# 8. isolation: no forbidden terms anywhere in the repo's own files
def test_no_forbidden_terms():
    terms = ["scor" + "ing", "regis" + "try", "plant" + "ed", "detection" + "_keys",
             "intended" + "_reach", "answer" + " key"]
    skip = {".git", ".venv", "data", "runs", "__pycache__", ".pytest_cache"}
    hits = []
    for p in ROOT.rglob("*"):
        if not p.is_file() or any(part in skip for part in p.relative_to(ROOT).parts):
            continue
        try:
            text = p.read_text(encoding="utf-8").lower()
        except UnicodeDecodeError:
            continue
        hits += [(str(p.relative_to(ROOT)), t) for t in terms if t in text]
    assert hits == []


# 9. a rejected call is set aside (never deleted) and retried on rerun
def test_rejected_call_kept_and_retried(cfg, monkeypatch):
    from src import llm as llm_mod
    real = llm_mod._stub_text
    state = {"bad": True}

    def flaky(stage, prompt):
        if stage == "notes" and "Matter: A-2" in prompt and state["bad"]:
            return "this is not json"
        return real(stage, prompt)

    monkeypatch.setattr(llm_mod, "_stub_text", flaky)
    assert cli.main(["notes"], cfg=cfg) == 1
    notes_dir = next(cfg.runs_root.glob("notes_*"))
    calls = notes_dir / "calls"
    assert not (calls / "notes_A-2.json").exists()
    rejected = calls / "notes_A-2.rejected.json"
    assert rejected.exists() and "rejected_reason" in read_json(rejected)
    assert (calls / "notes_A-2.rejected.prompt.txt").exists()
    first_usage = len(read_jsonl(notes_dir / "usage.jsonl"))
    assert first_usage == 2  # A-1 and the rejected A-2 call stay logged

    state["bad"] = False
    assert cli.main(["notes", "--run", str(notes_dir)], cfg=cfg) == 0
    assert (calls / "notes_A-2.json").exists()          # fresh call made
    assert rejected.exists()                            # rejected record kept
    assert len(read_jsonl(notes_dir / "usage.jsonl")) == first_usage + 3  # A-2 again, B-1, C-1
    assert len(read_jsonl(notes_dir / "notes.jsonl")) == 12


# 10. one stable cwd per run, shared by stateless, stateful and resumed calls; removed at the end
def test_single_cwd_per_run(cfg, tmp_path):
    cwds, cmds = [], []

    def runner(cmd, **kw):
        cwds.append(kw["cwd"])
        cmds.append(cmd)
        assert Path(kw["cwd"]).is_dir() and not any(Path(kw["cwd"]).iterdir())
        return subprocess.CompletedProcess(cmd, 0, stdout=SAMPLE, stderr="")

    llm = LLM(cfg, tmp_path, "r", "C1", live=True, runner=runner, environ={})
    a = llm.call("downstream", "s", "c1", "p1")
    b = llm.call("downstream", "s", "c2", "p2", stateful=True)
    llm.call("downstream", "s", "c3", "p3", session_id=b.session_id, stateful=True)
    assert len(cwds) == 3 and len(set(cwds)) == 1
    assert "--resume" in cmds[2]
    assert not Path(cwds[0]).resolve().is_relative_to(ROOT.resolve()) if hasattr(Path, "is_relative_to") \
        else not str(Path(cwds[0]).resolve()).startswith(str(ROOT.resolve()))
    llm.close()
    assert not Path(cwds[0]).exists()


# 11. entries that are not objects are rejected
def test_non_dict_entries_rejected(cfg):
    from src.stores import StageError
    with pytest.raises(StageError):
        stages.validate_scope(json.dumps({"items": ["a.01"]}), ["a.01"], cfg)
    with pytest.raises(StageError):
        stages.validate_scope(json.dumps({"items": [None]}), ["a.01"], cfg)
    with pytest.raises(StageError):
        stages.validate_patterns(json.dumps({"patterns": ["a pattern"]}), cfg)
    with pytest.raises(StageError):
        stages.validate_patterns(json.dumps({"patterns": [["x"]]}), cfg)


# 12. smoke runs five calls, resume reuses the stateful session
def test_smoke_five_calls(cfg, capsys):
    assert cli.main(["smoke"], cfg=cfg) == 0
    d = next(cfg.runs_root.glob("*_smoke"))
    assert len(read_jsonl(d / "usage.jsonl")) == 5
    st, rs = read_json(d / "calls" / "smoke_L2_stateful.json"), read_json(d / "calls" / "smoke_L2_resume.json")
    assert st["session_id_in"] is None and rs["session_id_in"] == st["session_id"]
    assert "reply:" in capsys.readouterr().out


# 13. rejected-call count lands in the manifest
def test_manifest_counts_rejected(cfg, monkeypatch):
    from src import llm as llm_mod
    real = llm_mod._stub_text
    monkeypatch.setattr(llm_mod, "_stub_text",
                        lambda stage, prompt: "nope" if stage == "notes" and "Matter: A-1" in prompt else real(stage, prompt))
    assert cli.main(["notes"], cfg=cfg) == 1
    d = next(cfg.runs_root.glob("notes_*"))
    assert read_json(d / "manifest.json")["rejected_calls"] == 1


# 10. N0: empty-store control
def _n0_and_c1(cfg):
    _run(cfg, ["notes"])
    notes_dir = next(cfg.runs_root.glob("notes_*"))
    _run(cfg, ["run", "--condition", "C1", "--notes", str(notes_dir)])
    _run(cfg, ["run", "--condition", "N0"])
    return (next(cfg.runs_root.glob("2*_C1")), next(cfg.runs_root.glob("2*_N0")))


def test_n0_outputs_stores_manifest(cfg):
    from src.stores import EMPTY_STORE_MARKER
    c1, n0 = _n0_and_c1(cfg)
    out, c1_out = read_jsonl(n0 / "probe_outputs.jsonl"), read_jsonl(c1 / "probe_outputs.jsonl")
    assert len(out) == 24 and set(out[0]) == set(c1_out[0]) and out[0]["condition"] == "N0"
    for name in ("client_A", "client_B", "client_C", "firm"):
        assert load_store(n0 / "stores" / (name + ".jsonl")) == []
    assert read_jsonl(n0 / "ledger.jsonl") == []
    m, m1 = read_json(n0 / "manifest.json"), read_json(c1 / "manifest.json")
    assert m["condition"] == "N0" and m["memory"] is False and m["notes_dir"] is None
    assert m["models"] and m["empty_store_substitution"] == EMPTY_STORE_MARKER == "(empty)"
    assert m["downstream_prompt_hash"] == m1["downstream_prompt_hash"] == \
        sha256_text((ROOT / "prompts" / "downstream.md").read_text(encoding="utf-8"))
    assert m1["memory"] is True


def test_n0_prompt_matches_c1_after_slot_swap(cfg):
    c1, n0 = _n0_and_c1(cfg)
    tmpl = cfg.prompt("downstream")
    for p in stages.load_probes(cfg):
        name = "calls/down_%s.prompt.txt" % p["id"]
        a, b = (n0 / name).read_text(), (c1 / name).read_text()
        assert a.count("(empty)") == 2
        matter = p["new_matter"]
        client = exclude_walled(load_store(c1 / "stores" / ("client_%s.jsonl" % cfg.client_letter(matter))), matter)
        firm = exclude_walled(load_store(c1 / "stores" / "firm.jsonl"), matter)
        swapped = tmpl.substitute(client=cfg.client_name(matter), matter=matter, probe=p["text"],
                                  client_store="(empty)", firm_store="(empty)")
        assert a == swapped
        assert b == tmpl.substitute(client=cfg.client_name(matter), matter=matter, probe=p["text"],
                                    client_store=render_items(client), firm_store=render_items(firm))


def test_n0_makes_no_gate_or_notes_calls(cfg):
    _, n0 = _n0_and_c1(cfg)
    usage = read_jsonl(n0 / "usage.jsonl")
    assert len(usage) == 24 and {u["stage"] for u in usage} == {"downstream"}
    assert not (n0 / "gate_raw").exists()
    assert not list((n0 / "calls").glob("scope_*")) and not list((n0 / "calls").glob("notes_*"))
    assert not list((n0 / "calls").glob("abstraction*"))
    assert [stages.planned_calls(cfg, s, "N0") for s in ("scope", "abstract")] == [[], []]


def test_condition_choices_from_config(cfg, capsys):
    with pytest.raises(SystemExit):
        cli.main(["run", "--condition", "ZZ"], cfg=cfg)
    assert "N0" in capsys.readouterr().err
