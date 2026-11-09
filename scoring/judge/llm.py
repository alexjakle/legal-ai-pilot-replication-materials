"""The only way the judge calls a model. Own code; ../pipeline/src/llm.py was read for behaviour only.

Every call is logged to usage.jsonl; its prompt and response are saved under calls/. A call whose saved
record has the same prompt hash is skipped; a different hash stops the run. A response the validator
rejects is renamed *.rejected* (usage row stays). One logged retry on a transient error."""
import json
import os
import re
import shutil
import subprocess
import tempfile
import time

from .util import append_jsonl, iso_now, read_json, sha256_text, write_json, write_text

TRANSIENT = re.compile(r"overloaded|\b(500|502|503|504|529)\b|ECONNRESET|ETIMEDOUT|temporarily unavailable", re.I)


class LLMError(Exception):
    exit_status = "error"


class ApiKeyPresent(LLMError):
    pass


class HashMismatch(LLMError):
    pass


class MaxCallsExceeded(LLMError):
    pass


class TransientError(LLMError):
    exit_status = "transient_error"


class LiveGuardError(Exception):
    pass


def check_no_api_key(environ=None):
    env = os.environ if environ is None else environ
    if "ANTHROPIC_API_KEY" in env:
        raise ApiKeyPresent("ANTHROPIC_API_KEY is set. This judge uses the subscription login only; "
                            "unset it (unset ANTHROPIC_API_KEY) and rerun.")


def live_guard(repo_dir, environ=None, runner=None):
    """No API key; scoring git tree clean, ignoring scores/."""
    check_no_api_key(environ)
    run = runner or subprocess.run
    p = run(["git", "status", "--porcelain", "--", ".", ":(exclude)scores"], cwd=repo_dir,
            capture_output=True, text=True)
    if p.returncode != 0:
        raise LiveGuardError("git status failed: %s" % p.stderr.strip())
    if p.stdout.strip():
        raise LiveGuardError("scoring git tree is not clean (ignoring scores/); commit or stash first:\n"
                             + p.stdout.rstrip())


def parse_result(stdout):
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
        raise (TransientError if TRANSIENT.search(msg) else LLMError)("claude reported an error: %.500s" % msg)
    u = obj.get("usage") or {}
    return {"text": obj["result"], "session_id": obj.get("session_id"),
            "input_tokens": u.get("input_tokens", 0), "output_tokens": u.get("output_tokens", 0),
            "cache_write_tokens": u.get("cache_creation_input_tokens", 0),
            "cache_read_tokens": u.get("cache_read_input_tokens", 0),
            "total_cost_usd": obj.get("total_cost_usd"), "duration_ms": obj.get("duration_ms"),
            "model_usage": obj.get("modelUsage")}


def assert_outside_repo(path):
    p = os.path.realpath(path)
    while True:
        if os.path.exists(os.path.join(p, ".git")):
            raise LLMError("working directory %s is inside a git repo (%s)" % (path, p))
        parent = os.path.dirname(p)
        if parent == p:
            return
        p = parent


class ClaudeCliBackend:
    name = "claude_cli"

    def __init__(self, model, system_prompt, timeout=1200, runner=None, environ=None, cwd=None):
        self.model, self.system_prompt, self.timeout = model, system_prompt, timeout
        self.runner = runner or subprocess.run
        self.environ = environ
        self.cwd = cwd

    def check_env(self):
        check_no_api_key(self.environ)

    def build_command(self):
        # L2 overhead flags. Never --bare.
        return ["claude", "-p", "--output-format", "json", "--model", self.model,
                "--tools", "", "--system-prompt", self.system_prompt, "--disable-slash-commands",
                "--strict-mcp-config", "--setting-sources", "", "--no-session-persistence"]

    def complete(self, prompt):
        self.check_env()
        try:
            proc = self.runner(self.build_command(), input=prompt, capture_output=True, text=True,
                               cwd=self.cwd, timeout=self.timeout, env=dict(os.environ))
        except subprocess.TimeoutExpired:
            raise TransientError("claude timed out after %ss" % self.timeout)
        if proc.returncode != 0:
            try:
                json.loads(proc.stdout)
            except ValueError:
                pass
            else:
                parse_result(proc.stdout)
            msg = (proc.stderr or proc.stdout or "")[:500]
            raise (TransientError if TRANSIENT.search(msg) else LLMError)(
                "claude exited with status %s: %s" % (proc.returncode, msg))
        return parse_result(proc.stdout)


class Rejected(Exception):
    pass


class JudgeClient:
    """call() returns the validated parsed object, or None if the validator rejected the response."""

    def __init__(self, backend, model, run_id, out_dir, max_calls=None, sleep=time.sleep, retry_sleep=5):
        self.backend, self.model, self.run_id = backend, model, run_id
        self.out_dir = out_dir
        self.calls_dir = os.path.join(out_dir, "calls")
        self.max_calls, self.made, self.sleep, self.retry_sleep = max_calls, 0, sleep, retry_sleep
        self.rejected_this_session = 0

    # --- saved records
    def rec_path(self, call_id):
        return os.path.join(self.calls_dir, call_id + ".json")

    def reject(self, call_id, reason):
        n, tag = 1, "rejected"
        while os.path.exists(os.path.join(self.calls_dir, "%s.%s.json" % (call_id, tag))):
            n += 1
            tag = "rejected%d" % n
        rec, prompt = self.rec_path(call_id), os.path.join(self.calls_dir, call_id + ".prompt.txt")
        if os.path.exists(rec):
            data = read_json(rec)
            data["rejected_reason"] = reason
            write_json(os.path.join(self.calls_dir, "%s.%s.json" % (call_id, tag)), data)
            os.unlink(rec)
        if os.path.exists(prompt):
            os.rename(prompt, os.path.join(self.calls_dir, "%s.%s.prompt.txt" % (call_id, tag)))
        self.rejected_this_session += 1

    def count_rejected(self):
        if not os.path.isdir(self.calls_dir):
            return 0
        return len([f for f in os.listdir(self.calls_dir) if re.search(r"\.rejected\d*\.json$", f)])

    def _validate(self, call_id, text, validator):
        try:
            return validator(text)
        except Exception as e:
            self.reject(call_id, str(e))
            return None

    def call(self, call_id, prompt, validator, stage, condition):
        phash = sha256_text(prompt)
        path = self.rec_path(call_id)
        if os.path.exists(path):
            rec = read_json(path)
            if rec["prompt_hash"] != phash:
                raise HashMismatch("call %s has a saved response from a different prompt (%s). The prompt "
                                   "or inputs changed; start a new scores folder, or delete the record "
                                   "and its .prompt.txt yourself." % (call_id, path))
            parsed = self._validate(call_id, rec["text"], validator)
            if parsed is not None:
                return parsed
        if self.max_calls is not None and self.made >= self.max_calls:
            raise MaxCallsExceeded("--max-calls %d reached; stopping before the next call" % self.max_calls)
        self.made += 1
        write_text(os.path.join(self.calls_dir, call_id + ".prompt.txt"), prompt)
        usage_path = os.path.join(self.out_dir, "usage.jsonl")
        for attempt in (0, 1):
            t0 = time.time()
            try:
                p = self.backend.complete(prompt)
                break
            except LLMError as e:
                lat = int((time.time() - t0) * 1000)
                retrying = isinstance(e, TransientError) and attempt == 0
                append_jsonl(usage_path, self._usage(stage, condition, call_id, None, e.exit_status + (":retrying" if retrying else ""), lat))
                if retrying:
                    self.sleep(self.retry_sleep)
                    continue
                raise
        lat = int((time.time() - t0) * 1000)
        ts = iso_now()
        row = self._usage(stage, condition, call_id, p, 0, lat, ts)
        append_jsonl(usage_path, row)
        write_json(path, {"call_id": call_id, "prompt_hash": phash, "stage": stage, "model": self.model,
                          "timestamp": ts, "text": p["text"], "usage": row, "backend": self.backend.name,
                          "session_id": p.get("session_id"), "model_usage": p.get("model_usage")})
        return self._validate(call_id, p["text"], validator)

    def _usage(self, stage, condition, call_id, p, exit_status, latency, ts=None):
        p = p or {}
        return {"run_id": self.run_id, "timestamp": ts or iso_now(), "stage": stage, "condition": condition,
                "role": "judge", "model": self.model, "call_id": call_id,
                "input_tokens": p.get("input_tokens"), "output_tokens": p.get("output_tokens"),
                "cache_read_tokens": p.get("cache_read_tokens"), "cache_write_tokens": p.get("cache_write_tokens"),
                "total_cost_usd": p.get("total_cost_usd"),
                "latency_ms": p.get("duration_ms") if p.get("duration_ms") is not None else latency,
                "exit_status": exit_status}


def make_workdir():
    d = tempfile.mkdtemp(prefix="judge_run_")
    assert_outside_repo(d)
    return d


def preflight_table(rows, model, backend):
    """rows: [(kind, count, chars)]. Returns text."""
    lines = ["Preflight: backend=%s model=%s" % (backend, model),
             "%-22s %6s %12s %12s" % ("calls", "n", "prompt chars", "~tokens")]
    tn = tc = 0
    for kind, n, chars in rows:
        lines.append("%-22s %6d %12d %12d" % (kind, n, chars, chars // 4))
        tn += n
        tc += chars
    lines.append("%-22s %6d %12d %12d" % ("total", tn, tc, tc // 4))
    return "\n".join(lines)


def confirm_live(input_fn=input):
    return input_fn("Type 'yes' to run these calls live: ").strip() == "yes"
