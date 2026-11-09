#!/usr/bin/env bash
# Release checks. Makes no model calls and needs no login or API key.
# Run from a clone of the repository (two audit checks read git state).
set -u
cd "$(dirname "$0")/.."
PY="${PYTHON:-python3}"
fails=0
skips=0

run() {   # run <label> <dir> <command...>
  local label="$1" dir="$2"; shift 2
  if (cd "$dir" && "$@" >/dev/null 2>&1); then
    echo "PASS  $label"
  else
    echo "FAIL  $label"; fails=$((fails + 1))
  fi
}

echo "== inputs"
if cmp -s pipeline/data/probes.jsonl scoring/probes.jsonl; then echo "PASS  probes: pipeline copy matches scoring"; else echo "FAIL  probes differ"; fails=$((fails + 1)); fi
if diff -r firm pipeline/data/firm >/dev/null 2>&1; then echo "PASS  pipeline/data/firm matches firm/"; else echo "FAIL  firm copies differ"; fails=$((fails + 1)); fi

echo "== confirmatory analysis reproduces the shipped report"
tmp="$(mktemp -d)"
if (cd scoring && "$PY" confirmatory.py confirmatory_conf.json --out "$tmp" --label CONFIRMATORY >/dev/null 2>&1) \
   && cmp -s "$tmp/confirmatory_confirmatory.md" scoring/confirmatory_out/confirmatory_confirmatory.md \
   && cmp -s "$tmp/confirmatory_confirmatory.json" scoring/confirmatory_out/confirmatory_confirmatory.json; then
  echo "PASS  confirmatory report identical"
else
  echo "FAIL  confirmatory report differs"; fails=$((fails + 1))
fi
rm -rf "$tmp"

echo "== answer key and document checks"
run "registry"   scoring "$PY" check_registry.py
run "collisions" scoring "$PY" audit/check_collisions.py
run "isolation"  scoring "$PY" audit/check_isolation.py
run "probes"     scoring "$PY" audit/check_probes.py

echo "== tests"
if "$PY" -c "import pytest, yaml" >/dev/null 2>&1; then
  run "pipeline tests" pipeline "$PY" -m pytest -q
  run "scoring tests"  scoring  "$PY" -m pytest -q
else
  echo "SKIP  tests (pytest and PyYAML not installed; see REPLICATION.md, Setup)"; skips=$((skips + 1))
fi

echo
echo "failed: $fails  skipped: $skips"
[ "$fails" -eq 0 ]
