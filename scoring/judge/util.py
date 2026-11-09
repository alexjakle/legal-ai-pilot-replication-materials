"""Small shared helpers (standard library only)."""
import datetime
import hashlib
import json
import os
import re
import tempfile

_QUOTES = {"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-", " ": " "}


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def sha256_text(s):
    return sha256_bytes(s.encode("utf-8"))


def norm(s):
    """Whitespace-, case-, quote-style- and markdown-emphasis-normalized form used for every quote check."""
    for a, b in _QUOTES.items():
        s = s.replace(a, b)
    s = re.sub(r"[*`]", "", s)
    return re.sub(r"\s+", " ", s).strip().lower()


def iso_now():
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()


def read_jsonl(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _atomic(path, text):
    d = os.path.dirname(path) or "."
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".tmp_")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def write_jsonl(path, rows):
    _atomic(path, "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows))


def append_jsonl(path, row):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def write_json(path, obj):
    _atomic(path, json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def write_text(path, text):
    _atomic(path, text)


def read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)
