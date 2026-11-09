"""Stub backend: canned judgments, no model call. Default responder says `verbatim` for a row whose
text appears in the judged text and `absent` otherwise, and returns one candidate if the judged
text contains the marker STUBCAND."""
import json
import re


def split_prompt(prompt):
    rows = []
    for m in re.finditer(r"^(R\d+) \| type: (\S+) \| reach: (\S+) \| client: (\S+) \| matter: (\S+) \| text: (.*)$",
                         prompt, re.M):
        rows.append({"label": m.group(1), "type": m.group(2), "text": m.group(6)})
    a, b = prompt.rfind("<<<TEXT_START>>>\n"), prompt.rfind("\n<<<TEXT_END>>>")
    return rows, prompt[a + len("<<<TEXT_START>>>\n"):b]


def default_responder(prompt):
    rows, text = split_prompt(prompt)
    low = text.lower()
    out = []
    for r in rows:
        hit = r["text"].lower() in low
        out.append({"label": r["label"], "verdict": "verbatim" if hit else "absent", "quote": r["text"] if hit else ""})
    cands = []
    if "STUBCAND" in text:
        cands.append({"output_quote": "STUBCAND", "apparent_reach": "client", "note": "stub candidate"})
    return json.dumps({"rows": out, "unregistered_candidates": cands})


class StubBackend:
    name = "stub"

    def __init__(self, responder=None):
        self.responder = responder or default_responder
        self.prompts = []

    def check_env(self):
        pass

    def complete(self, prompt):
        self.prompts.append(prompt)
        return {"text": self.responder(prompt), "session_id": None, "input_tokens": 0, "output_tokens": 0,
                "cache_write_tokens": 0, "cache_read_tokens": 0, "total_cost_usd": 0.0, "duration_ms": 0,
                "model_usage": None}
