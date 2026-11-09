"""Read the clean firm export and check it against a run manifest. Reimplements the pipeline's
tree hash (sha256 over sorted relative path + NUL + bytes + NUL) without importing pipeline code."""
import hashlib
import os
import re


def firm_docs(firm_dir):
    """{relative path: text} for every file in the export."""
    docs = {}
    for root, _, files in os.walk(firm_dir):
        for f in files:
            p = os.path.join(root, f)
            rel = os.path.relpath(p, firm_dir)
            with open(p, encoding="utf-8", errors="ignore") as fh:
                docs[rel] = fh.read()
    return docs


def hash_tree(firm_dir):
    paths = []
    for root, _, files in os.walk(firm_dir):
        for f in files:
            paths.append(os.path.join(root, f))
    h = hashlib.sha256()
    for p in sorted(paths, key=lambda p: os.path.relpath(p, firm_dir)):
        h.update(os.path.relpath(p, firm_dir).encode("utf-8") + b"\0")
        with open(p, "rb") as fh:
            h.update(fh.read() + b"\0")
    return h.hexdigest()


def read_tag(tag_path):
    out = {}
    with open(tag_path, encoding="utf-8") as f:
        for line in f:
            m = re.match(r"\s*(\w+):\s*(\S+)", line)
            if m:
                out[m.group(1)] = m.group(2)
    return out


def check_against_manifest(firm_dir, tag_path, run_manifest):
    """Return (problems, info). A problem means the export is not the one the run used."""
    problems = []
    mf = run_manifest.get("firm", {})
    tag = read_tag(tag_path) if os.path.exists(tag_path) else {}
    if tag.get("tag") != mf.get("tag"):
        problems.append("FIRM_TAG tag %r != run manifest tag %r" % (tag.get("tag"), mf.get("tag")))
    if tag.get("commit") != mf.get("commit"):
        problems.append("FIRM_TAG commit %r != run manifest commit %r" % (tag.get("commit"), mf.get("commit")))
    h = hash_tree(firm_dir)
    if h != mf.get("data_hash"):
        problems.append("firm export hash %s != run manifest data_hash %s" % (h, mf.get("data_hash")))
    return problems, {"tag": tag.get("tag"), "commit": tag.get("commit"), "data_hash": h}
