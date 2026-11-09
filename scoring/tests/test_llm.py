import json
import subprocess

import pytest

from judge import llm
from judge.llm import JudgeClient, LLMError, TransientError
from judge.stub import StubBackend


def ok(t):
    if t != "good":
        raise ValueError("bad")
    return {"ok": 1}


def client(tmp_path, responder, **kw):
    be = StubBackend(responder)
    return JudgeClient(be, "stub", "RUN", str(tmp_path), sleep=lambda s: None, **kw), be


def test_rejected_response_is_set_aside_and_counted(tmp_path):
    c, be = client(tmp_path, lambda p: "bad")
    assert c.call("c1", "prompt", ok, "judge_probe", "C0") is None
    names = sorted(p.name for p in (tmp_path / "calls").iterdir())
    assert names == ["c1.rejected.json", "c1.rejected.prompt.txt"]
    assert c.count_rejected() == 1
    usage = [json.loads(l) for l in open(tmp_path / "usage.jsonl")]
    assert len(usage) == 1 and usage[0]["exit_status"] == 0
    assert json.load(open(tmp_path / "calls" / "c1.rejected.json"))["rejected_reason"] == "bad"
    c.responder = None
    c2, _ = client(tmp_path, lambda p: "good")          # a rerun calls afresh
    assert c2.call("c1", "prompt", ok, "judge_probe", "C0") == {"ok": 1}


def test_skip_on_same_hash_and_stop_on_mismatch(tmp_path):
    c, be = client(tmp_path, lambda p: "good")
    c.call("c1", "prompt", ok, "s", "C0")
    c.call("c1", "prompt", ok, "s", "C0")
    assert len(be.prompts) == 1
    with pytest.raises(llm.HashMismatch):
        c.call("c1", "different prompt", ok, "s", "C0")


def test_max_calls(tmp_path):
    c, be = client(tmp_path, lambda p: "good", max_calls=1)
    c.call("a", "p1", ok, "s", "C0")
    c.call("a", "p1", ok, "s", "C0")                   # skipped calls do not count
    with pytest.raises(llm.MaxCallsExceeded):
        c.call("b", "p2", ok, "s", "C0")


def test_one_logged_retry_on_transient(tmp_path):
    state = {"n": 0}

    class Flaky(StubBackend):
        def complete(self, prompt):
            state["n"] += 1
            if state["n"] == 1:
                raise TransientError("overloaded 529")
            return super().complete(prompt)

    c = JudgeClient(Flaky(lambda p: "good"), "stub", "RUN", str(tmp_path), sleep=lambda s: None)
    assert c.call("a", "p", ok, "s", "C0") == {"ok": 1}
    st = [json.loads(l)["exit_status"] for l in open(tmp_path / "usage.jsonl")]
    assert st == ["transient_error:retrying", 0]

    class Dead(StubBackend):
        def complete(self, prompt):
            raise TransientError("overloaded")

    c = JudgeClient(Dead(), "stub", "RUN2", str(tmp_path / "x"), sleep=lambda s: None)
    with pytest.raises(TransientError):
        c.call("a", "p", ok, "s", "C0")
    assert len(open(tmp_path / "x" / "usage.jsonl").readlines()) == 2


def test_live_guards(tmp_path):
    with pytest.raises(llm.ApiKeyPresent):
        llm.live_guard(str(tmp_path), {"ANTHROPIC_API_KEY": "x"})
    subprocess.run(["git", "init", "-q"], cwd=tmp_path)
    (tmp_path / "scores").mkdir()
    (tmp_path / "scores" / "a.txt").write_text("x")
    llm.live_guard(str(tmp_path), {})                  # scores/ ignored
    (tmp_path / "dirty.py").write_text("x")
    with pytest.raises(llm.LiveGuardError):
        llm.live_guard(str(tmp_path), {})
    assert llm.confirm_live(lambda p: "yes") and not llm.confirm_live(lambda p: "y")
    assert not llm.confirm_live(lambda p: "")


def test_claude_command_flags_and_api_key_refusal(tmp_path):
    seen = {}

    def runner(cmd, **kw):
        seen["cmd"], seen["kw"] = cmd, kw
        out = json.dumps({"type": "result", "result": "hi", "usage": {"input_tokens": 3}, "total_cost_usd": 0.1})
        return subprocess.CompletedProcess(cmd, 0, out, "")

    be = llm.ClaudeCliBackend("claude-opus-5-5", "Follow.", runner=runner, environ={}, cwd=str(tmp_path))
    p = be.complete("hello")
    cmd = seen["cmd"]
    assert p["text"] == "hi" and "--bare" not in cmd
    for flag in ("--no-session-persistence", "--disable-slash-commands", "--strict-mcp-config"):
        assert flag in cmd
    assert cmd[cmd.index("--tools") + 1] == "" and cmd[cmd.index("--setting-sources") + 1] == ""
    assert cmd[cmd.index("--model") + 1] == "claude-opus-5-5" and cmd[cmd.index("--system-prompt") + 1] == "Follow."
    assert seen["kw"]["input"] == "hello" and seen["kw"]["cwd"] == str(tmp_path)
    with pytest.raises(llm.ApiKeyPresent):
        llm.ClaudeCliBackend("m", "s", runner=runner, environ={"ANTHROPIC_API_KEY": "k"}).complete("x")


def test_workdir_is_outside_a_repo():
    d = llm.make_workdir()
    try:
        llm.assert_outside_repo(d)
    finally:
        import shutil
        shutil.rmtree(d)
