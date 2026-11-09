# Replication guide

Three levels, cheapest first. All commands assume you are at the repository root.

## Setup

Python 3.9 or newer. The saved runs used 3.9.6.

```
python3 -m venv .venv
. .venv/bin/activate
pip install -r pipeline/requirements.txt
```

`pipeline/requirements.txt` and `scoring/requirements.txt` pin the same two packages (pytest 8.4.2, PyYAML 6.0.3).

## Level 1: verify without model calls

Everything here uses saved files only. No login, no API key, no cost.

**All release checks at once:**

```
./scripts/verify.sh
```

Run it in a clone of the repository. Two of the audit checks read git state, so they need a git repository.

**Regenerate the confirmatory analysis.** This needs only the Python standard library.

```
cd scoring
python3 confirmatory.py confirmatory_conf.json --out /tmp/conf_check --label CONFIRMATORY
cmp /tmp/conf_check/confirmatory_confirmatory.md confirmatory_out/confirmatory_confirmatory.md
cmp /tmp/conf_check/confirmatory_confirmatory.json confirmatory_out/confirmatory_confirmatory.json
```

The output lists the seven declared predictions with PASS or FAIL. `cmp` prints nothing when the files match.

**Rederive a run's scores from its saved judgments.** This makes no model call. It rewrites the derived files in the scores folder, so run it in a clone and check git afterwards.

```
cd scoring
python3 run_judge.py finalize ../pipeline/runs/20261103T174207Z_C0 scores/20261103T174207Z_C0
git status --short .
```

Two files in that scores folder will show as modified, `manifest.json` and `report.md`. They change only in bookkeeping: a new `created` time, the current scoring commit hash, `made_this_session` becoming 0 because no calls were made, and `firm_export` set to null. Every other file, including `judgments.jsonl`, `scores.jsonl` and `row_scores.jsonl`, should be unchanged. Run `git restore scores` afterwards to undo the rewrite.

**Run the tests.**

```
(cd pipeline && python3 -m pytest -q)
(cd scoring && python3 -m pytest -q)
```

**Run the answer-key and document checks.**

```
cd scoring
python3 check_registry.py
python3 audit/check_collisions.py
python3 audit/check_isolation.py
python3 audit/check_probes.py
```

All four should end with PASS. `audit/check_fuzzy.py` ends with FAIL by design, on seven pairs of near-identical letterheads and boilerplate between documents. They were reviewed by hand and judged to be noise. The saved outputs of earlier audit runs are in `scoring/audit/results/`, with personal paths removed.

## Level 2: rejudge the saved outputs

This runs the judge (Claude Opus 5.5) live on probe outputs already in `pipeline/runs/`.

Requirements: the Claude Code CLI installed and logged in, `ANTHROPIC_API_KEY` not set, and a clean git tree outside `scoring/scores/`. The judge asks you to type yes after printing how many calls it will make.

```
cd scoring
python3 run_judge.py judge ../pipeline/runs/20261103T174207Z_C0 --repeat
```

- It writes a new scores folder next to the shipped one and never overwrites it. A rejudge of an already judged run gets a `__2` suffix.
- `--repeat` also judges the fixed subset of 20 outputs a second time (seed 20261019), to measure the judge's own consistency.
- Each run is about 28 to 35 judge calls. For scale, judging the eight confirmatory runs took roughly 6 to 9 points of a weekly allowance per replicate on a Claude plan.
- The judge prompt (`scoring/judge/prompts/judge.md`, v2) is frozen. If you change it, say so, because the validation described in the paper applies only to that prompt.

To build a combined report across several scores folders:

```
python3 run_judge.py report scores/<run_a> scores/<run_b> --name my_report
```

To rerun the confirmatory analysis on your own judged runs, copy `confirmatory_conf.json`, replace its eight paths with your scores folders, and run `confirmatory.py` as above.

## Level 3: rerun from scratch

This regenerates notes, stores and probe answers from the locked firm. It calls Claude Sonnet 5.5, and the pipeline uses no other service.

Requirements are as in Level 2, plus these:

- `pipeline/data/FIRM_TAG` and `pipeline/data/firm/` are the locked inputs. Do not edit them. The pipeline reads the firm only from `pipeline/data/firm`.
- Keep any agent session away from `scoring/` while you run (contract rule 1).
- Live runs refuse a dirty git tree. The check ignores `pipeline/runs/`.

```
cd pipeline
python3 -m src.cli notes --live
python3 -m src.cli run --condition C0 --notes runs/notes_<timestamp> --live
python3 -m src.cli run --condition C1 --notes runs/notes_<timestamp> --live
python3 -m src.cli run --condition C2 --notes runs/notes_<timestamp> --live
python3 -m src.cli run --condition N0 --live
```

- Without `--live`, every command uses a stub backend and makes no model calls. Use it to check the plan first.
- Each live command prints a preflight table with the number of calls per stage and waits for a typed yes. `--max-calls N` caps the total.
- All conditions in one replicate share one notes run. N0 makes no notes or gate calls.
- Each call's prompt and response are saved under `runs/<run_id>/calls/`, token usage in `usage.jsonl`, and versions, hashes and the Claude Code version in `manifest.json`. Runs are never overwritten, and a run stopped by a usage limit can resume with `--run runs/<run_id>`.
- Settings are in `pipeline/config/` (`pipeline.yaml`, `conditions.yaml`, `walls.yaml`), and the prompts are plain files in `pipeline/prompts/`.

Then judge the new runs as in Level 2 and compare with the confirmatory report.

## What you should expect

- Level 1 should match the shipped files exactly.
- Level 2 should be close to the shipped judgments but not identical, because a judge is a model. The saved repeat judgments show how much it varied (36 of 40, or 90.0%, in agreement on family sets, which is exactly at the bar and lower for condition C2).
- Level 3 will differ in wording and probably in counts. The question is whether the qualitative pattern holds, not whether the numbers match. The two confirmatory replicates, and the gap between them and the development runs, are a guide to how much run-to-run variation to expect.

## Known gaps

- The prompts used to generate and edit the 16 firm documents, and to run the seeder and the audits, are not stored as separate files here. The locked documents and the registry are.
- Session transcripts are not included. They hold full working conversations.
- The pre-rename drafts of the firm documents (the firm had an earlier name) are not included. The locked firm in `firm/` is what every run used.
