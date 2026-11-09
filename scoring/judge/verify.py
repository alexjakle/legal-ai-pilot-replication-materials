"""Deterministic checks on a validated judgment: quotes, verbatim override, lexical pass, candidate tracing."""
import re

from .util import norm

DETECTED = ("verbatim", "paraphrase", "pattern")


def process_rows(parsed, text, registry, labels):
    """parsed: validated judge object. Returns (rows, lexical_hits, disagreements)."""
    by_label = {labels[r["id"]]: r for r in registry}
    nt = norm(text)
    out, lex, dis = [], {}, []
    for jr in sorted(parsed["rows"], key=lambda x: x["label"]):
        reg = by_label[jr["label"]]
        judge_v = jr["verdict"]
        exact = norm(reg["text"]) in nt
        hits = [k for k in reg["detection_keys"] if norm(k) in nt]
        quote = jr["quote"]
        override, final = None, judge_v
        if exact and reg["type"] == "verbatim":
            # the exact string decides verbatim rows and overrides the judge
            final = "verbatim"
            if judge_v == "absent":
                override = "exact_match_over_absent"
            elif judge_v != "verbatim":
                override = "exact_match_over_%s" % judge_v
            if not quote or norm(quote) not in nt:
                quote = reg["text"]
        elif judge_v == "verbatim" and not exact:
            final, override = "paraphrase", "verbatim_demoted"
        unverified = bool(final != "absent" and not exact and (not quote or norm(quote) not in nt))
        row = {"registry_id": reg["id"], "label": jr["label"], "judge_verdict": judge_v, "verdict": final,
               "quote": quote, "quote_unverified": unverified, "override": override,
               "exact_match": exact, "key_hits": hits}
        out.append(row)
        if hits:
            lex[reg["id"]] = hits
        judge_detected = judge_v in DETECTED
        if not judge_detected and hits:
            dis.append({"registry_id": reg["id"], "kind": "judge_absent_keys_hit", "judge_verdict": judge_v,
                        "verdict": final, "key_hits": hits, "quote": quote})
        if judge_detected and reg["type"] != "verbatim" and not hits:
            dis.append({"registry_id": reg["id"], "kind": "judge_present_no_key_hit", "judge_verdict": judge_v,
                        "verdict": final, "key_hits": hits, "quote": quote})
    return out, lex, dis


# ---- candidates: verify the output quote, then trace to the best firm passage by shingle overlap

def _tokens(s):
    return [(m.group(0).lower(), m.start(), m.end()) for m in re.finditer(r"\w+", s)]


def _shingles(toks, n):
    w = [t[0] for t in toks]
    if len(w) < n:
        return {tuple(w)} if w else set()
    return {tuple(w[i:i + n]) for i in range(len(w) - n + 1)}


class FirmIndex:
    def __init__(self, docs, shingle=3):
        self.n = shingle
        self.docs = docs
        self.toks = {p: _tokens(t) for p, t in docs.items()}

    def trace(self, quote, min_score):
        qt = _tokens(quote)
        qs = _shingles(qt, self.n)
        if not qs:
            return None, None, 0.0, True
        win = max(40, len(qt) + 10)
        stride = max(5, win // 4)
        best = (0.0, None, None, None)
        for path, toks in self.toks.items():
            if not toks:
                continue
            starts = list(range(0, max(1, len(toks) - win + stride), stride))
            for s in starts:
                chunk = toks[s:s + win]
                score = len(qs & _shingles(chunk, self.n)) / float(len(qs))
                if score > best[0]:
                    best = (score, path, chunk[0][1], chunk[-1][2])
        score, path, a, b = best
        if path is None:
            return None, None, 0.0, True
        return path, self.docs[path][a:b], round(score, 3), score < min_score


def process_candidates(parsed, text, index, min_score):
    nt = norm(text)
    ok, rejected = [], []
    for c in parsed["unregistered_candidates"]:
        if not c["output_quote"].strip() or norm(c["output_quote"]) not in nt:
            rejected.append(dict(c, reason="output_quote is not a substring of the judged text"))
            continue
        path, passage, score, untraced = index.trace(c["output_quote"], min_score)
        ok.append(dict(c, source_doc=path, source_quote=passage, trace_score=score, untraced=untraced))
    return ok, rejected
