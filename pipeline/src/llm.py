"""The only way pipeline code calls a model.

Every call is logged to the run's usage.jsonl, its full prompt and response are
saved under calls/, and a call whose record already exists is skipped (only when
the stored prompt hash matches).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from .config import Config, sha256_text
from .runfs import append_jsonl, iso_now, write_json, write_text

OVERHEAD_LEVELS = ("L0", "L1", "L2")
_TRANSIENT = re.compile(r"overloaded|\b(500|502|503|504|529)\b|ECONNRESET|ETIMEDOUT|temporarily unavailable", re.I)


class LLMError(Exception):
    exit_status = "error"


class ApiKeyPresent(LLMError):
    pass


class PromptMismatch(LLMError):
    pass


class MaxCallsExceeded(LLMError):
    pass


class TransientError(LLMError):
    exit_status = "transient_error"


@dataclass
class Result:
    text: str
    session_id: Optional[str]
    usage: dict
    timestamp: str
    skipped: bool = False


def check_no_api_key(environ=None) -> None:
    env = os.environ if environ is None else environ
    if "ANTHROPIC_API_KEY" in env:
        raise ApiKeyPresent(
            "ANTHROPIC_API_KEY is set in this environment. This pipeline uses the "
            "subscription login only. Unset it (unset ANTHROPIC_API_KEY) and rerun."
        )


def parse_result(stdout: str) -> dict:
    """Parse the JSON printed by `claude -p --output-format json`."""
    try:
        obj = json.loads(stdout)
    except ValueError as e:
        raise LLMError("claude output is not JSON: %s: %.200s" % (e, stdout))
    if isinstance(obj, list):
        obj = next((o for o in obj if isinstance(o, dict) and o.get("type") == "result"), None)
        if obj is None:
            raise LLMError("claude output has no result object")
    if obj.get("is_error"):
        msg = str(obj.get("result"))
        raise (TransientError if _TRANSIENT.search(msg) else LLMError)("claude reported an error: %.500s" % msg)
    u = obj.get("usage") or {}
    return {
        "text": obj["result"],
        "session_id": obj.get("session_id"),
        "input_tokens": u.get("input_tokens", 0),
        "output_tokens": u.get("output_tokens", 0),
        "cache_write_tokens": u.get("cache_creation_input_tokens", 0),
        "cache_read_tokens": u.get("cache_read_input_tokens", 0),
        "total_cost_usd": obj.get("total_cost_usd"),
        "duration_ms": obj.get("duration_ms"),
        "model_usage": obj.get("modelUsage"),
    }


def usage_row(run_id, stage, condition, role, model, parsed, exit_status, latency_ms, timestamp=None) -> dict:
    p = parsed or {}
    return {
        "run_id": run_id,
        "timestamp": timestamp or iso_now(),
        "stage": stage,
        "condition": condition,
        "role": role,
        "model": model,
        "session_id": p.get("session_id"),
        "input_tokens": p.get("input_tokens"),
        "output_tokens": p.get("output_tokens"),
        "cache_write_tokens": p.get("cache_write_tokens"),
        "cache_read_tokens": p.get("cache_read_tokens"),
        "total_cost_usd": p.get("total_cost_usd"),
        "latency_ms": p.get("duration_ms") if p.get("duration_ms") is not None else latency_ms,
        "exit_status": exit_status,
    }


class StubBackend:
    """Canned text; makes no model call."""

    name = "stub"

    def complete(self, prompt, session_id, stateful, overhead, stage, role):
        text = _stub_text(stage, prompt)
        sid = ("stub-" + sha256_text(prompt)[:8]) if (stateful or session_id) else None
        return {
            "text": text, "session_id": sid, "input_tokens": 0, "output_tokens": 0,
            "cache_write_tokens": 0, "cache_read_tokens": 0, "total_cost_usd": 0.0,
            "duration_ms": 0, "model_usage": None,
        }


def _stub_text(stage: str, prompt: str) -> str:
    if stage == "notes":
        return json.dumps({"items": [
            {"type": "fact", "text": "Stub fact."},
            {"type": "position", "text": "Stub position."},
            {"type": "lesson", "text": "Stub lesson."}]})
    if stage == "scope_gate":
        ids = re.findall(r"^- \[([^\]]+)\]", prompt, re.M)
        matter = re.search(r"^Matter: (\S+)", prompt, re.M).group(1)
        items = []
        for i, item_id in enumerate(ids):
            tags = ["wall:A-3"] if (matter == "A-2" and i == 0) else []
            items.append({"id": item_id, "decision": "client_store", "tags": tags})
        return json.dumps({"items": items})
    if stage == "abstraction_gate":
        ids, seen, picks = [], set(), []
        client = None
        for line in prompt.splitlines():
            if line.startswith("### "):
                client = line[4:]
            m = re.match(r"^- \[([^\]]+)\]", line)
            if m and client not in seen:
                seen.add(client)
                picks.append(m.group(1))
        return json.dumps({"patterns": [{"text": "Stub pattern.", "contributing_items": picks, "tags": []}]})
    if stage == "downstream":
        return "STUB ANSWER"
    return "ok"


class ClaudeCliBackend:
    name = "claude_cli"

    def __init__(self, model, overhead="L0", system_prompt="", timeout=900, runner=None, environ=None,
                 cwd=None):
        self.cwd = cwd  # one stable empty dir per run; None means a throwaway dir per call
        self.model = model
        self.overhead = overhead
        self.system_prompt = system_prompt
        self.timeout = timeout
        self.runner = runner or subprocess.run
        self.environ = environ

    def check_env(self):
        check_no_api_key(self.environ)

    def build_command(self, session_id=None, stateful=False, overhead=None) -> list:
        level = overhead or self.overhead
        if level not in OVERHEAD_LEVELS:
            raise LLMError("unknown overhead level %r" % level)
        cmd = ["claude", "-p", "--output-format", "json", "--model", self.model]
        if level in ("L1", "L2"):
            cmd += ["--tools", ""]
        if level == "L2":
            cmd += ["--system-prompt", self.system_prompt, "--disable-slash-commands",
                    "--strict-mcp-config", "--setting-sources", ""]
        if session_id:
            cmd += ["--resume", session_id]
        elif not stateful:
            cmd.append("--no-session-persistence")
        return cmd

    def complete(self, prompt, session_id, stateful, overhead, stage, role):
        self.check_env()
        cmd = self.build_command(session_id, stateful, overhead)
        cwd = self.cwd or tempfile.mkdtemp(prefix="llm_call_")
        try:
            try:
                proc = self.runner(cmd, input=prompt, capture_output=True, text=True,
                                   cwd=cwd, timeout=self.timeout, env=dict(os.environ))
            except subprocess.TimeoutExpired:
                raise TransientError("claude timed out after %ss" % self.timeout)
        finally:
            if not self.cwd:
                shutil.rmtree(cwd, ignore_errors=True)
        if proc.returncode != 0:
            try:
                json.loads(proc.stdout)
            except ValueError:
                pass
            else:
                parse_result(proc.stdout)  # raises with claude's own message if is_error
            msg = (proc.stderr or proc.stdout or "")[:500]
            err = TransientError if _TRANSIENT.search(msg) else LLMError
            raise err("claude exited with status %s: %s" % (proc.returncode, msg))
        return parse_result(proc.stdout)


class CodexCliBackend:
    name = "codex_cli"

    def __init__(self, *a, **k):
        pass

    def check_env(self):
        pass

    def complete(self, *a, **k):
        raise NotImplementedError(
            "codex_cli backend is a stub and is not implemented yet. "
            "Set the backend to claude_cli in config/pipeline.yaml."
        )


class CallBudget:
    def __init__(self, max_calls: Optional[int]):
        self.max_calls = max_calls
        self.used = 0

    def take(self):
        if self.max_calls is not None and self.used >= self.max_calls:
            raise MaxCallsExceeded("--max-calls %d reached; stopping before the next call" % self.max_calls)
        self.used += 1


class LLM:
    def __init__(self, cfg: Config, run_dir: Path, run_id: str, condition: str,
                 live: bool = False, budget: Optional[CallBudget] = None,
                 runner: Optional[Callable] = None, sleep: Callable = time.sleep, environ=None):
        self.cfg = cfg
        self.run_dir = Path(run_dir)
        self.run_id = run_id
        self.condition = condition
        self.live = live
        self.budget = budget
        self.runner = runner
        self.sleep = sleep
        self.environ = environ
        self.cwd: Optional[str] = None
        if live:
            for role in cfg.pipeline["roles"]:
                self._backend(role).check_env()
            # One empty cwd for every claude call in this run, so a resumed session
            # runs from the directory it was created in. Outside any repo.
            self.cwd = tempfile.mkdtemp(prefix="llm_run_")
            root = str(cfg.root.resolve()) + os.sep
            if (str(Path(self.cwd).resolve()) + os.sep).startswith(root):
                self.close()
                raise LLMError("system temp dir is inside the repository; set TMPDIR elsewhere")

    def close(self) -> None:
        if self.cwd:
            shutil.rmtree(self.cwd, ignore_errors=True)
            self.cwd = None

    def _backend(self, role, overhead=None):
        if not self.live:
            return StubBackend()
        rc = self.cfg.role(role)
        cc = self.cfg.pipeline.get("claude_cli", {})
        if rc["backend"] == "claude_cli":
            return ClaudeCliBackend(rc["model"], overhead or cc.get("overhead", "L0"),
                                    cc.get("system_prompt", ""), cc.get("timeout_s", 900),
                                    self.runner, self.environ, self.cwd)
        if rc["backend"] == "codex_cli":
            return CodexCliBackend()
        raise LLMError("unknown backend %r for role %s" % (rc["backend"], role))

    def model_for(self, role):
        return self.cfg.role(role)["model"]

    def reject(self, call_id: str, reason: str) -> None:
        """Set aside a call whose output a stage refused. Nothing is deleted: the record and
        prompt are renamed to <id>.rejected[N].*, usage rows stay, and a rerun calls afresh."""
        calls = self.run_dir / "calls"
        rec, prompt = calls / (call_id + ".json"), calls / (call_id + ".prompt.txt")
        n, tag = 1, "rejected"
        while (calls / ("%s.%s.json" % (call_id, tag))).exists():
            n += 1
            tag = "rejected%d" % n
        if rec.exists():
            data = json.loads(rec.read_text(encoding="utf-8"))
            data["rejected_reason"] = reason
            write_json(calls / ("%s.%s.json" % (call_id, tag)), data)
            rec.unlink()
        if prompt.exists():
            prompt.rename(calls / ("%s.%s.prompt.txt" % (call_id, tag)))

    def call(self, role, stage, call_id, prompt, session_id=None, stateful=False, overhead=None) -> Result:
        calls = self.run_dir / "calls"
        rec_path = calls / (call_id + ".json")
        phash = sha256_text(prompt)
        if rec_path.exists():
            rec = json.loads(rec_path.read_text(encoding="utf-8"))
            if rec["prompt_hash"] != phash:
                raise PromptMismatch(
                    "Call %s already has a saved response from a different prompt. "
                    "The prompts or inputs changed since that run. Start a new run, or "
                    "delete %s and its .prompt.txt if you mean to redo this call."
                    % (call_id, rec_path))
            return Result(rec["text"], rec["session_id"], rec["usage"], rec["timestamp"], skipped=True)
        backend = self._backend(role, overhead)
        model = self.model_for(role)
        if self.budget:
            self.budget.take()
        write_text(calls / (call_id + ".prompt.txt"), prompt)
        usage_path = self.run_dir / "usage.jsonl"
        for attempt in (0, 1):
            t0 = time.time()
            try:
                parsed = backend.complete(prompt, session_id, stateful, overhead, stage, role)
                break
            except LLMError as e:
                latency = int((time.time() - t0) * 1000)
                append_jsonl(usage_path, usage_row(self.run_id, stage, self.condition, role, model,
                                                   None, e.exit_status + (":retrying" if isinstance(e, TransientError) and attempt == 0 else ""),
                                                   latency))
                if isinstance(e, TransientError) and attempt == 0:
                    self.sleep(self.cfg.pipeline.get("claude_cli", {}).get("retry_sleep_s", 5))
                    continue
                raise
        latency = int((time.time() - t0) * 1000)
        ts = iso_now()
        row = usage_row(self.run_id, stage, self.condition, role, model, parsed, 0, latency, ts)
        append_jsonl(usage_path, row)
        write_json(rec_path, {
            "call_id": call_id, "prompt_hash": phash, "stage": stage, "role": role, "model": model,
            "condition": self.condition, "timestamp": ts, "session_id_in": session_id,
            "session_id": parsed["session_id"], "text": parsed["text"], "usage": row,
            "model_usage": parsed.get("model_usage"), "backend": backend.name,
        })
        return Result(parsed["text"], parsed["session_id"], row, ts)
