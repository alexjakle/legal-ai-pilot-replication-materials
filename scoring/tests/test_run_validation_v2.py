"""run_validation.py --set v2 with the stub backend only. No model calls."""
import json
import os
import sys

import pytest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import run_judge  # noqa: E402
import run_validation  # noqa: E402
from judge.util import read_json  # noqa: E402
from tests.test_validation import fixture_prompt_hash, live_manifest  # noqa: E402,F401

V2_ID = "validation_v2_20261028"


def v2_env(env, set_name="v2"):
    items = [{"id": "W01", "text": "Please note the Larkspur review. STUBCAND here."},
             {"id": "W02", "text": "Nothing registered in this text."}]
    ipath = env["tmp"] / "items_v2.jsonl"
    ipath.write_text("".join(json.dumps(i) + "\n" for i in items))
    paths = env["paths"]
    paths.items, paths.check_live, paths.set_name = str(ipath), False, set_name
    return paths


def test_default_set_is_v1_unchanged():
    p = run_validation.default_paths()
    assert p.set_name == "v1" and p.items.endswith(os.path.join("validation", "items.jsonl"))
    assert run_validation.run_id_for({"shuffle_seed": 20261019}) == "validation_20261019"
    assert run_validation.default_paths("v2").items.endswith(os.path.join("validation", "v2", "items.jsonl"))
    assert run_validation.run_id_for({"shuffle_seed": 20261019}, "v2") == V2_ID


def test_v2_run_id_folder_and_manifest(env):
    paths = v2_env(env)
    d = run_validation.run(paths=paths, stub=True, out=lambda s: None)
    assert os.path.basename(d) == V2_ID and os.path.dirname(d) == paths.scores_root
    m = read_json(os.path.join(d, "manifest.json"))
    assert m["run_id"] == V2_ID and m["set"] == "v2" and m["status"] == "complete" and m["stub"] is True
    assert m["items_hash"] == run_judge.file_hash(paths.items)
    assert m["items_file"].replace(os.sep, "/") == "validation/v2/items.jsonl"
    assert not os.path.exists(os.path.join(paths.scores_root, "validation_20261019"))
    # finalize reads the same folder
    run_validation.run(paths=paths, finalize_only=True, out=lambda s: None)


def test_v1_manifest_names_set_v1(env):
    paths = v2_env(env, "v1")
    d = run_validation.run(paths=paths, stub=True, out=lambda s: None)
    assert os.path.basename(d) == "validation_20261019"
    assert read_json(os.path.join(d, "manifest.json"))["set"] == "v1"


def test_v2_needs_pre_rejudge_when_hash_differs_and_manifest_carries_notice(env):
    paths = v2_env(env)
    paths.check_live = True
    live_manifest(paths.scores_root, "0" * 64)
    with pytest.raises(SystemExit, match="prompt hash"):
        run_validation.run(paths=paths, stub=True, out=lambda s: None)
    assert not os.path.exists(os.path.join(paths.scores_root, V2_ID))
    paths.pre_rejudge = True
    shown = []
    d = run_validation.run(paths=paths, stub=True, out=shown.append)
    m = read_json(os.path.join(d, "manifest.json"))
    assert m["pre_rejudge"] is True and "not yet usable as a result" in m["pre_rejudge_notice"]
    assert any(s.startswith("PRE-REJUDGE") for s in shown)


def test_set_flag_parsed(env, monkeypatch):
    seen = {}

    def fake_run(paths=None, **kw):
        seen["paths"], seen["kw"] = paths, kw

    monkeypatch.setattr(run_validation, "run", fake_run)
    run_validation.main(["--stub", "--set", "v2", "--pre-rejudge"])
    assert seen["paths"].set_name == "v2" and seen["paths"].pre_rejudge and seen["kw"]["stub"]
    run_validation.main(["--stub"])
    assert seen["paths"].set_name == "v1"
    with pytest.raises(SystemExit):
        run_validation.main(["--set", "v3"])
