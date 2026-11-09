"""Shared helpers for the judge validation set (standard library plus judge.util). Python 3.9."""
import glob
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from judge.util import norm, read_json, read_jsonl  # noqa: E402

SEED = 20261019
WORDS_LO, WORDS_HI = 240, 480
RUNS_DIR = os.path.join(ROOT, "..", "pipeline", "runs")
STRENGTH = {"verbatim": "verbatim", "paraphrase": "paraphrase", "client_pattern": "pattern", "area_pattern": "pattern"}
STRENGTHS = ("verbatim", "paraphrase", "pattern")
ABBREV = {"mr", "mrs", "ms", "dr", "no", "v", "vs", "inc", "co", "corp", "ltd", "st", "e.g", "i.e", "etc", "cf"}

# composition by construction slot kind
COMPOSITION = [("verbatim", 8), ("paraphrase", 8), ("client_pattern", 8), ("area_pattern", 4), ("multi", 2),
               ("near_miss", 6), ("none", 4)]


def word_count(text):
    return len(text.split())


def key_hits(text, row):
    nt = norm(text)
    return [k for k in row["detection_keys"] if norm(k) in nt]


def exact_hit(text, row):
    return norm(row["text"]) in norm(text)


def family_of(row_id):
    m = re.match(r"^([ABCP][12])-", row_id)
    return m.group(1) if m else None


def load_pool(runs_dir=RUNS_DIR, lo=WORDS_LO, hi=WORDS_HI):
    """Probe outputs of the live condition runs (C0, C1, C2), 240-480 words. Sorted, deterministic."""
    pool = []
    for d in sorted(glob.glob(os.path.join(runs_dir, "*_C[012]"))):
        p = os.path.join(d, "probe_outputs.jsonl")
        if not os.path.exists(p):
            continue
        for o in read_jsonl(p):
            w = word_count(o["text"])
            if lo <= w <= hi:
                pool.append({"run_id": o["run_id"], "condition": o["condition"], "probe_id": o["probe_id"],
                             "words": w, "text": o["text"]})
    return sorted(pool, key=lambda b: (b["run_id"], b["probe_id"]))


def live_manifests(scores_root):
    """Manifests of the complete, non-stub pipeline-run judgments under scores/ (validation runs excluded).
    A run judged more than once (scores/<run>, scores/<run>__2, ...) contributes only its latest judgment:
    the highest __N folder suffix, no suffix counting as 1. Incomplete judgments never supersede."""
    latest = {}
    for p in sorted(glob.glob(os.path.join(scores_root, "*", "manifest.json"))):
        m = read_json(p)
        if m.get("stub") or m.get("kind") == "validation" or m.get("status") != "complete" or "source_run" not in m:
            continue
        sfx = re.search(r"__(\d+)$", os.path.basename(os.path.dirname(p)))
        n = int(sfx.group(1)) if sfx else 1
        key = m["run_id"]  # manifest["source_run"] is a provenance dict; run_id is shared by every judgment of a run
        if key not in latest or n > latest[key][0]:
            latest[key] = (n, m)
    return [m for _, m in latest.values()]


def parse_near_misses(md):
    """[{section, family, quote}] for every quoted lookalike; the out-of-scope section is skipped."""
    out, sec, fam = [], None, None
    for line in md.splitlines():
        if line.startswith("## "):
            sec = line[3:].strip()
            m = re.match(r"Not (\w\d) ", sec)
            fam = m.group(1) if m else ("RETENTION" if "retention" in sec.lower() else None)
            if sec.startswith("Out of scope"):
                sec = None
            continue
        if sec and line.startswith("- "):
            m = re.search(r'— "(.*?)"(?:\s*\(.*\))?\s*$', line)
            if m:
                out.append({"section": sec, "family": fam, "quote": m.group(1)})
    return out


# ---------------------------------------------------------------- insertion

def _marker_len(line):
    """Length of a leading list marker ('- ', '* ', '2. ', '3) ') including indentation, else 0."""
    m = re.match(r"\s*(?:[-*+]|\d+[.)])\s+", line)
    return m.end() if m else 0


def _boundaries(line):
    """Offsets just after each sentence end in a line (the end of the line included). A list marker
    such as '2.' is not a sentence end."""
    out = []
    start = _marker_len(line)
    for m in re.finditer(r"[.!?][\"')\]*]*(?=\s|$)", line):
        if m.end() <= start:
            continue
        before = line[:m.start()].split()
        last = before[-1].lower().strip("*(\"'") if before else ""
        if m.group(0).startswith(".") and (last in ABBREV or re.fullmatch(r"[a-z]", last)):
            continue
        out.append(m.end())
    out = [o for o in out if o > start]
    if not out or out[-1] != len(line.rstrip()):
        out.append(len(line.rstrip()))
    return out


def eligible_lines(text):
    """Indexes of lines that are prose (paragraph or bullet item) of at least 8 words, outside code fences."""
    lines, fence, idx = text.split("\n"), False, []
    for i, ln in enumerate(lines):
        if ln.strip().startswith("```"):
            fence = not fence
            continue
        s = ln.strip()
        if fence or not s or s.startswith("#") or s.startswith("|") or s.startswith("---"):
            continue
        body = re.sub(r"^([-*+]|\d+[.)])\s+", "", s)
        if (body.startswith("**") and body.endswith("**")) or body.endswith(":"):
            continue
        if len(body.split()) >= 8 and re.search(r"[A-Za-z]{3}", body):
            idx.append(i)
    return idx


def insert_sentences(text, inserts):
    """inserts: [(sentence, seed)]. Each goes at a seeded sentence boundary inside a seeded prose line;
    two inserts never share a line. Returns (new_text, [{line, offset}])."""
    import random
    lines = text.split("\n")
    used, places = set(), []
    for sentence, seed in inserts:
        rng = random.Random(seed)
        cands = [i for i in eligible_lines(text) if i not in used]
        if not cands:
            raise ValueError("no eligible paragraph for insertion")
        i = rng.choice(cands)
        used.add(i)
        b = rng.choice(_boundaries(lines[i]))
        places.append((i, b, sentence))
    for i, b, sentence in places:
        ln = lines[i]
        lines[i] = ln[:b].rstrip() + " " + sentence.strip() + (" " + ln[b:].lstrip() if ln[b:].strip() else "")
    return "\n".join(lines), [{"line": i, "offset": b} for i, b, _ in places]
