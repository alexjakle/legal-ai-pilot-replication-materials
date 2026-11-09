"""Assemble the judge prompt: opaque row labels, relabelled near-miss text, text last."""
import os
import random
import re

from .util import sha256_text

HERE = os.path.dirname(os.path.abspath(__file__))
PROMPT_PATH = os.path.join(HERE, "prompts", "judge.md")
FAMILY = re.compile(r"\b([ABC][12]|P[12])\b")
DROP_SECTION = "## Out of scope for pattern detection"


def family_of(row_id):
    m = re.match(r"^([ABCP][12])-", row_id)
    return m.group(1) if m else None


def make_labels(registry, seed):
    """{registry_id: 'R01'..} from a seeded shuffle of the registry order."""
    ids = [r["id"] for r in registry]
    random.Random(seed).shuffle(ids)
    return {rid: "R%02d" % (i + 1) for i, rid in enumerate(ids)}


def render_near_misses(md, registry, labels):
    """Replace family names (A1, C2, P1 ...) with the row labels of that family, and drop the
    carrier-scope section (the scorer has no carrier rule). The file on disk is not changed."""
    cut = md.find(DROP_SECTION)
    if cut >= 0:
        md = md[:cut].rstrip() + "\n"
    fam = {}
    for r in registry:
        f = family_of(r["id"])
        if f:
            fam.setdefault(f, []).append(labels[r["id"]])
    return FAMILY.sub(lambda m: "/".join(sorted(fam.get(m.group(1), [m.group(1)]))), md)


def render_rows(registry, labels):
    lines = []
    for r in sorted(registry, key=lambda r: labels[r["id"]]):
        lines.append("%s | type: %s | reach: %s | client: %s | matter: %s | text: %s" % (
            labels[r["id"]], r["type"], r["intended_reach"], r["client"], r["matter"], r["text"]))
    return "\n".join(lines)


class PromptBuilder:
    def __init__(self, registry, near_misses_md, labels, template=None):
        tpl = template if template is not None else open(PROMPT_PATH, encoding="utf-8").read()
        prefix, _, suffix = tpl.partition("{{TEXT}}")
        prefix = prefix.replace("{{ROWS}}", render_rows(registry, labels))
        prefix = prefix.replace("{{NEAR_MISSES}}", render_near_misses(near_misses_md, registry, labels))
        self.prefix, self.suffix = prefix, suffix
        self.labels = labels
        self.prefix_hash = sha256_text(prefix + suffix)

    def build(self, text):
        return self.prefix + text + self.suffix
