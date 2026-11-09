import ast
import glob
import os
import re

from judge.build_prompt import PromptBuilder, make_labels, render_near_misses
from judge.util import read_jsonl
from tests.conftest import HERE

FORBIDDEN = re.compile(r"\b(C0|C1|C2|A-3|B-2|C-2)\b")


def real_builder():
    reg = read_jsonl(os.path.join(HERE, "registry.jsonl"))
    near = open(os.path.join(HERE, "near_misses.md"), encoding="utf-8").read()
    return reg, near, PromptBuilder(reg, near, make_labels(reg, 20261019))


def test_prompt_is_blind():
    reg, near, pb = real_builder()
    prompt = pb.build("NEUTRAL TEXT")
    assert not FORBIDDEN.findall(prompt), FORBIDDEN.findall(prompt)
    probes = [p["id"] for p in read_jsonl(os.path.join(HERE, "probe_map.jsonl"))]
    for token in probes + ["20261019T232425Z_C0", "20261019T230656Z_C1", "_C0", "_C1", "_C2"] + [r["id"] for r in reg]:
        assert token not in prompt, token
    assert "firm-lock" not in prompt and "client_A" not in prompt and "matter_only" not in prompt


def test_prompt_has_no_detection_keys_and_no_firm_documents():
    reg, near, pb = real_builder()
    prompt = pb.build("NEUTRAL TEXT").lower()
    visible = prompt
    own = " ".join(r["text"].lower() for r in reg) + near.lower()
    unique = [k for r in reg for k in r["detection_keys"] if k.lower() not in own]
    assert unique and not [k for k in unique if k.lower() in visible]
    assert "detection_keys" not in prompt and "doc_path" not in prompt
    assert prompt.count("<<<text_start>>>") == 1 and "04-instruction-letter" in prompt   # near-miss paths only
    assert len(pb.build("")) < 40000                                                  # no 95 KB firm export


def test_near_misses_relabelled_and_carrier_section_dropped():
    reg, near, pb = real_builder()
    labels = make_labels(reg, 20261019)
    out = render_near_misses(near, reg, labels)
    assert "Out of scope for pattern detection" not in out and "also_in" not in out
    assert re.search(r"## Not R\d\d/R\d\d \(", out) or re.search(r"## Not R\d\d \(", out)
    assert not re.search(r"\b(A1|A2|B1|B2|C1|C2|P1|P2)\b", out)


def test_labels_are_a_seeded_permutation():
    reg = read_jsonl(os.path.join(HERE, "registry.jsonl"))
    a, b = make_labels(reg, 20261019), make_labels(reg, 20261019)
    assert a == b and sorted(a.values()) == ["R%02d" % i for i in range(1, 32)]
    assert [a[r["id"]] for r in reg] != sorted(a.values())   # shuffled relative to registry order


def test_nothing_in_scoring_imports_pipeline():
    files = [f for f in glob.glob(os.path.join(HERE, "**", "*.py"), recursive=True) if ".venv" not in f and "/audit/" not in f]
    assert files
    for f in files:
        for node in ast.walk(ast.parse(open(f, encoding="utf-8").read())):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            for n in names:
                assert n.split(".")[0] not in ("pipeline", "src"), (f, n)
