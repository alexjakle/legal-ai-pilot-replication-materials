import json

import sampler


def pids():
    return ["%s-%s%d" % (m, k, i) for m in ("A3", "B2", "C2") for k, n in (("T", 4), ("F", 2), ("X", 2)) for i in range(1, n + 1)]


def test_deterministic_and_sizes():
    a, b = sampler.sample(pids()), sampler.sample(list(reversed(pids())))
    assert a == b
    assert [len(a[c]) for c in ("C0", "C1", "C2")] == [7, 7, 6]
    assert all(set(v) <= set(pids()) and len(set(v)) == len(v) for v in a.values())


def test_stratified_by_kind_and_seed_matters():
    a = sampler.sample(pids())
    for v in a.values():
        kinds = [sampler.probe_kind(p) for p in v]
        assert kinds.count("T") >= 3 and kinds.count("F") >= 1 and kinds.count("X") >= 1
    assert sampler.sample(pids(), seed=1) != a
    assert sampler.SEED == 20261019
