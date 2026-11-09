"""compare.py family rule and adjudicated corrections on a synthetic set. No model calls, no real labels."""
import os
import sys

import pytest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "validation"))

import compare  # noqa: E402

REG_IDS = ["P1-A-1", "P1-A-2", "P1-B-1", "F01", "F02", "F03"]
ITEMS = ["T1", "T2", "T3", "T4", "T5", "T6"]

# Alex's rows and the judge's rows per item
ALEX = {"T1": {"P1-A-1"}, "T2": {"P1-A-1", "P1-B-1"}, "T3": {"F01"}, "T4": {"F02"}, "T5": {"F03"}, "T6": {"P1-A-1"}}
JUDGE = {"T1": {"P1-A-2"},        # sibling only: family match, strict mismatch
         "T2": {"P1-A-1", "P1-B-1"},  # strict match; row-No on P1-A-1 keeps family (sibling remains)
         "T3": {"F01"},           # strict match; family-No removes F01 from key -> judge FP stays
         "T4": set(),             # judge missed F02; row-Yes on F02 changes nothing about judge
         "T5": {"F03"},           # strict match; no ruling
         "T6": set()}             # judge missed P1-A-1; family-No on P1 removes it -> key empty -> match


@pytest.fixture
def fams(tmp_path):
    p = tmp_path / "families.json"
    p.write_text('{"P1-A-1": "P1", "P1-A-2": "P1", "P1-B-1": "P1"}')
    return compare.load_families(str(p), REG_IDS)


def md(tmp_path, name, body):
    p = tmp_path / name
    p.write_text(body)
    return str(p)


GOOD_ROWS = """# Title
Write `Ruling: yes` somewhere in the preamble.

## Case 1: T2, row P1-A-1

text

Ruling: No 

---

## Case 2: T4, row F02 (note)

Ruling: Yes
"""
GOOD_FAMS = """## Case 1: T3, family F01 (a description)

Ruling: No

## Case 2: T6, family P1 (x)

Ruling: No
"""


def test_three_figures(tmp_path, fams):
    assert fams["P1-A-2"] == "P1" and fams["F01"] == "F01"
    rulings = compare.parse_adjudication([md(tmp_path, "a.md", GOOD_ROWS), md(tmp_path, "b.md", GOOD_FAMS)],
                                         set(ITEMS), fams)
    assert rulings == [("T2", "row", "P1-A-1", False), ("T4", "row", "F02", True),
                       ("T3", "family", "F01", False), ("T6", "family", "P1", False)]
    strict = [i for i in ITEMS if JUDGE[i] == ALEX[i]]
    assert strict == ["T2", "T3", "T5"]
    fam = compare.family_agreement(ITEMS, JUDGE, ALEX, fams)
    assert fam == ["T1", "T2", "T3", "T5"]
    corr = compare.family_agreement(ITEMS, JUDGE, ALEX, fams, rulings)
    # T1 match; T2 family kept (P1-B-1 remains) so match; T3 key loses F01, judge still has it -> mismatch;
    # T4 key gains F02, judge empty -> mismatch; T5 match; T6 key empty -> match
    assert corr == ["T1", "T2", "T5", "T6"]


def test_row_no_removes_family_when_no_sibling_left(tmp_path, fams):
    key = compare.corrected_key(["T1"], {"T1": {"P1-A-1"}}, [("T1", "row", "P1-A-1", False)], fams)
    assert key["T1"] == set()


def test_report_shows_three_figures_and_verdict_on_strict(tmp_path):
    res = {"n": 40, "matches": list(range(17)), "fam_matches": list(range(25)), "corr_matches": list(range(36))}
    text = "\n".join(compare.three_figures(res))
    assert "strict blind (primary) | 17 of 40" in text
    assert "family rule | 25 of 40" in text and "post-hoc, not validation" in text
    assert "family rule plus adjudicated corrections | 36 of 40" in text
    res["corr_matches"] = None
    assert "not run" in "\n".join(compare.three_figures(res))


@pytest.mark.parametrize("body,msg", [
    ("## Case 1: T1, row F01\n\nno ruling here\n", "exactly one Ruling"),
    ("## Case 1: T1, row F01\n\nRuling: Maybe\n", "Yes or No"),
    ("## Case 1: T9, row F01\n\nRuling: Yes\n", "unknown item"),
    ("## Case 1: T1, row ZZ9\n\nRuling: Yes\n", "unknown row"),
    ("## Case 1: T1, family ZZ\n\nRuling: Yes\n", "unknown family"),
    ("## Case 1: T1 row F01\n\nRuling: Yes\n", "malformed case header"),
    ("## Case 1: T1, row F01\nRuling: Yes\n## Case 2: T1, row F01\nRuling: No\n", "duplicate"),
    ("## Case 1: T1, row F01\nRuling: Yes\nRuling: No\n", "exactly one Ruling"),
])
def test_parser_refuses(tmp_path, fams, body, msg):
    with pytest.raises(compare.Refuse, match=msg):
        compare.parse_adjudication([md(tmp_path, "x.md", body)], set(ITEMS), fams)


def test_families_file_refuses_unknown_row(tmp_path):
    p = tmp_path / "f.json"
    p.write_text('{"NOPE": "P1"}')
    with pytest.raises(compare.Refuse, match="unknown rows"):
        compare.load_families(str(p), REG_IDS)
