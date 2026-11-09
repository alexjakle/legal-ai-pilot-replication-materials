# Matter-boundary pilot: replication materials

Materials for a small experiment on memory boundaries in legal AI. A synthetic law firm, a four-condition pipeline that builds "memory" from earlier matters, and a blind LLM judge that checks what crosses the boundary into a new matter's answers.

Paper: _link to follow_

This is a first, small pilot with one generator model, four source matters and three synthetic clients. Its results are descriptive. It is not a benchmark, and nothing here shows how any real legal AI product behaves.

## The question

When a legal AI builds memory from past matters, what may it carry forward to the same client's next matter, and what may it carry to other clients or to the firm as a whole? The pilot tests this against a synthetic firm with planted facts and practices, so that anything that crosses a boundary can be found and counted.

## The testbed

- **Firm.** Kenge, Carboy & Vholes LLP, a fictional product-liability defense firm. Three invented manufacturer clients (A: cardiac pacing leads, B: pressure cookers, C: truck axles). Everything is invented, including people, courts and cases.
- **Source matters.** Four matters (A-1, A-2, B-1, C-1), four documents each: a draft answer, a discovery email thread, a case memo and a client instruction letter. 16 documents in `firm/`.
- **Planted content.** A registry of 31 rows in `scoring/registry.jsonl`: 8 verbatim facts, 8 paraphrase facts, 8 client patterns and 7 area patterns, each with an intended reach (matter, client or firm).
- **Probes.** 24 probes (`scoring/probes.jsonl`), eight for each of three new matters (A-3, B-2, C-2): topical, fishing and cross-scope questions. Each run answers all 24.
- **Conditions.**
  - `C0`: no gates. Every note goes straight into the stores. The positive control.
  - `C1`: a scope gate and an abstraction gate (a firm-level pattern needs at least two contributing clients), each call made fresh.
  - `C2`: the same gates, run as one continuing session.
  - `N0`: empty stores, same probes and prompt. Shows what the model produces with no memory at all.
- **Judge.** Claude Opus 5.5, blind to condition, with a frozen prompt (`scoring/judge/prompts/judge.md`). The notes, gates and downstream calls use Claude Sonnet 5.5.

## Read this before you read the numbers

- **The judge did not meet its validation bar.** Against a pre-declared 90% bar, judge prompt v1 matched 17 of 40 validation items (42%) and the revised v2 matched 27 of 40 (68%), on blind labels. A later adjudication of the 16 disputed v2 units, made with the judge's quotes in view and so open to anchoring, gives 37 of 40. That figure is post hoc and is not validation. All judged results should be read with this in mind.
- **Development and confirmatory runs are separate.** The first runs shaped the categories and rules and are reported as the development set. Two later replicates, run under a frozen prompt and pre-declared predictions, are the confirmatory set. Of seven declared predictions, five passed and two failed (3 and 4). The prediction-7 pass (judge self-consistency) is exactly at its bar.
- **Counts are per output and per family,** not per registry row. Runs within a condition are not independent observations.
- **With empty stores the model still produces some firm-level "patterns"** (the textbook practices P1 and P2), so detections at firm level mean something only above the `N0` baseline.
- **The registry was partly built after the documents.** A spec-first corpus is a design lesson for the next experiment, not something this pilot did.

The full account is in the paper. The confirmatory report is `scoring/confirmatory_out/confirmatory_confirmatory.md`.

## What is in the repository

```
CLAUDE.md                  The pilot contract as it governed the work
ORIGINAL_HISTORY.md        Maps the original commit hashes and tags to what they were
firm/                      The 16 synthetic documents (locked as firm-lock-v1)
pipeline/
  config/ prompts/ src/ tests/
  data/                    firm/ (clean copy of the locked firm), probes.jsonl, FIRM_TAG
  runs/                    Every run, with the full prompt and response of every call
scoring/
  registry.jsonl          The answer key (31 rows), near_misses.md, probe_map.jsonl, probes.jsonl
  judge/ scorer.py        The blind judge and the scorer
  run_judge.py report.py confirmatory.py
  confirmatory_conf.json  The eight confirmatory runs, as declared before judging
  confirmatory_out/        The confirmatory analysis
  validation/              Judge validation sets v1 and v2, blind labels, adjudication
  scores/                  Judgments and scores for every run
  audit/ review/          Consistency checks on the documents, and blind realism reviews
scripts/verify.sh          Release checks that make no model calls
```

`scoring/` holds the answer key. If you rerun the pipeline, keep agents away from it, as the contract (`CLAUDE.md`, rule 1) says.

During the pilot, `firm`, `pipeline` and `scoring` were three separate git repositories under one parent folder. This release puts them in one repository with the same folder names and layout, so relative paths still work. Run manifests record commit hashes from the original repositories, and `ORIGINAL_HISTORY.md` explains them.

## Runs

| Set | Notes run | Runs (in `pipeline/runs/`) |
| --- | --- | --- |
| Smoke test | none | `20261019T225859Z_smoke` |
| Development | `notes_20261019T230058Z` | `20261019T230656Z_C1`, `20261019T231541Z_C2`, `20261019T232425Z_C0` |
| Development (N0) | none | `20261022T022404Z_N0`, `20261028T164939Z_N0` |
| Confirmatory, replicate 1 | `notes_20261103T173800Z` | `20261103T174207Z_C0`, `20261103T175206Z_C1`, `20261103T180019Z_C2`, `20261103T180724Z_N0` |
| Confirmatory, replicate 2 | `notes_20261103T214649Z` | `20261103T221238Z_C0`, `20261103T220512Z_C1`, `20261103T215654Z_C2`, `20261103T215033Z_N0` |

Judgments for each run are in `scoring/scores/<run_id>/`. A folder ending in `__2` is a rejudge under the revised prompt, kept beside the original. Judge validation runs are `validation_20261019` and `validation_v2_20261028`.

## Replicating

`REPLICATION.md` has the commands. There are three levels of effort.

1. **Verify without model calls.** Run the tests, and regenerate the confirmatory analysis from the saved judgments. This is free and needs only Python.
2. **Rejudge.** Run the judge again on the saved probe outputs. This uses Claude Opus on your own plan or account.
3. **Rerun from scratch.** Regenerate notes, stores and probe answers from the locked firm. Results will not match exactly. See below.

## What will not reproduce exactly

Models change, and the outputs of a language model are not deterministic. The pipeline calls `claude -p` and cannot set temperature, which is recorded as `default` in every manifest. The saved runs used Claude Code 2.1.304 to 2.1.317 on macOS 26.5.2 with Python 3.9.6. A rerun will differ in wording and probably in counts. The two confirmatory replicates already differ from the development runs, which shows that the variation is real.

## Running it yourself

Live runs call the Claude Code CLI as a subprocess, using your own Claude login. You are responsible for checking that scripted use is permitted under the terms and usage limits that apply to your account. The code refuses to run if `ANTHROPIC_API_KEY` is set, because that would switch to API billing. I used a subscription only, and no API spend.

## How this was made

Claude and Claude Code helped design, build and analyze the pilot. Part of the aim was to learn how those tools approach research design. The firm's documents were generated by Claude Sonnet 5.5 and then edited and checked by hand and by separate review passes. `ORIGINAL_HISTORY.md` lists the commits in the order they were made.

## License

Code: MIT (`LICENSE`). Documents, registry, probes, run outputs and reports: CC BY 4.0 (`LICENSE-DATA.md`).

## Citing

_Citation to follow once the paper is published._
