"""Seeded stratified sampler for the consistency subset. Deterministic given the probe ids, the seed and quotas.
Strata: condition, then probe kind (T topical, F fishing, X cross-scope) with largest-remainder quotas."""
import random
import re

SEED = 20261019
QUOTAS = {"C0": 7, "C1": 7, "C2": 6}


def probe_kind(probe_id):
    m = re.search(r"-([A-Z])\d+$", probe_id)
    return m.group(1) if m else "?"


def _quotas(sizes, n):
    total = sum(sizes.values())
    raw = {k: n * v / float(total) for k, v in sizes.items()}
    q = {k: int(raw[k]) for k in sizes}
    for k in sorted(sizes, key=lambda k: (-(raw[k] - q[k]), k))[: n - sum(q.values())]:
        q[k] += 1
    return q


def sample(probe_ids, quotas=None, seed=SEED):
    """{condition: sorted list of probe ids}."""
    quotas = quotas or QUOTAS
    strata = {}
    for p in sorted(probe_ids):
        strata.setdefault(probe_kind(p), []).append(p)
    out = {}
    for cond in sorted(quotas):
        rng = random.Random("%s|%s" % (seed, cond))
        q = _quotas({k: len(v) for k, v in strata.items()}, quotas[cond])
        picked = []
        for k in sorted(strata):
            picked += rng.sample(strata[k], q[k])
        out[cond] = sorted(picked)
    return out
