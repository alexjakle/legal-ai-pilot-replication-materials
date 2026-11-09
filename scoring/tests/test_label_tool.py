"""validation/v2/make_label_tool.py: structure of the generated page. Reads items, registry and families.md only."""
import importlib.util
import json
import os
import re

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V2 = os.path.join(HERE, "validation", "v2")

spec = importlib.util.spec_from_file_location("make_label_tool", os.path.join(V2, "make_label_tool.py"))
mlt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mlt)


def built():
    items = mlt.read_jsonl(mlt.ITEMS)
    registry = mlt.read_jsonl(mlt.REGISTRY)
    units = mlt.build(items, registry, open(mlt.FAMILIES_MD, encoding="utf-8").read())
    return items, registry, units, mlt.render(items, units, "f" * 64)


def test_units_are_four_families_then_twenty_rows():
    _, registry, units, _ = built()
    assert [u["id"] for u in units[:4]] == ["A1", "A2", "P1", "P2"]
    assert [u["id"] for u in units[4:]] == ["F%02d" % n for n in range(1, 17)] + ["B1-B-1", "B2-B-1", "C1-C-1", "C2-C-1"]
    reg = {r["id"]: r for r in registry}
    assert all(u["ref"] == reg[u["id"]]["text"] for u in units[4:])
    assert all(u["ref"].startswith("Core: ") for u in units[:4]) and "Does not count: " in units[2]["ref"]
    assert sorted(r for u in units[:4] for r in u["rows"]) == sorted(r for r in reg if r[:2] in ("A1", "A2", "P1", "P2"))


def test_page_is_self_contained_and_embeds_items_only():
    items, _, units, html = built()
    assert not re.search(r"https?://|<link|\ssrc=|@import|fetch\(|XMLHttpRequest", html)
    m = re.search(r'id="items-data" type="application/json">(.*?)</script>', html, re.S)
    assert json.loads(m.group(1)) == items
    code = re.sub(r'(<script id="[a-z]+-data" type="application/json">).*?</script>', r"\1</script>", html, flags=re.S)
    assert "construction" not in code.lower() and "expected" not in code
    for tok in ("labels_v2.csv", "units_present", "localStorage", "None present", "Export CSV", "Export partial"):
        assert tok in html
    assert html.count("<script") == 3 and html.count("</script>") == 3


def test_item_text_cannot_break_out_of_the_script_tag():
    html = mlt.render([{"id": "X", "text": "</script><b>&</b>"}], [], "0" * 64)
    assert html.count("</script>") == 3 and "\\u003c/script\\u003e" in html
