# Original development history

This release is a fresh-history snapshot. During the pilot, `firm`, `pipeline` and `scoring` were three separate git repositories, and run manifests and the written record cite commit hashes and tags from them. This file maps those hashes to what they were. Author fields are omitted. Times are as committed (Pacific).

## firm

| Commit | Committed | Message |
| --- | --- | --- |
| `c0efb8b` | 2026-10-16 11:51 | firm: 16 documents, renamed to Kenge, Carboy & Vholes (pre-fix checkpoint) |
| `b1418a3` | 2026-10-16 11:52 | firm: human consistency fixes (A-2 review time, B-1 lot and report date, A-1 release year) |
| `58eb90f` | 2026-10-16 11:54 | firm: human consistency fixes (A-2 review time and mitigation defense, B-1 lot and report date, A-1 release year) |
| `ea805f3` | 2026-10-16 12:05 | firm: human consistency fixes (A-2 protective order timeline, A-1 CFO threshold, B-1 expert name) |
| `e28b9a1` | 2026-10-16 12:42 | firm: seed 16 planted facts (Step 3) |
| `d97fd90` | 2026-10-16 12:44 | firm: stop tracking .DS_Store |
| `dc5b317` | 2026-10-19 14:12 | Step 4b human fixes: arithmetic, protective-order wording, regulatory-path wording, SRM analysis, rollover terminology |

Tags (each points at the commit shown):

| Tag | Commit |
| --- | --- |
| `firm-lock-v1` | `dc5b317` |

## pipeline

| Commit | Committed | Message |
| --- | --- | --- |
| `978da3d` | 2026-10-19 15:58 | Step 5 pipeline: stages, stores, CLI, stub tests |
| `e2bca43` | 2026-10-19 16:06 | Notes run notes_20261019T230058Z and smoke run |
| `9c616c6` | 2026-10-19 16:15 | Run 20261019T230656Z_C1 |
| `cd8a444` | 2026-10-19 16:24 | Run 20261019T231541Z_C2 |
| `7a6b2e5` | 2026-10-19 16:32 | Run 20261019T232425Z_C0 |
| `16d2b38` | 2026-10-21 19:23 | Add N0 empty-store control condition |
| `bd1aa67` | 2026-10-28 09:49 | Run 20261022T022404Z_N0 |
| `5dbcbe5` | 2026-10-28 09:56 | Run 20261028T164939Z_N0 (second N0 run, development set, validation bases) |
| `93f3f57` | 2026-11-03 09:42 | Notes run notes_20261103T173800Z (confirmatory, replicate 1) |
| `b016f73` | 2026-11-03 09:52 | Run 20261103T174207Z_C0 (confirmatory, replicate 1) |
| `fff22f8` | 2026-11-03 10:00 | Run 20261103T175206Z_C1 (confirmatory, replicate 1) |
| `046f00b` | 2026-11-03 10:07 | Run 20261103T180019Z_C2 (confirmatory, replicate 1) |
| `9e8510c` | 2026-11-03 10:13 | Run 20261103T180724Z_N0 (confirmatory, replicate 1) |
| `6e42b5f` | 2026-11-03 13:49 | Notes 20261103T214649Z (confirmatory, replicate 2) |
| `cdde5a9` | 2026-11-03 13:56 | Run 20261103T215033Z_N0 (confirmatory, replicate 2) |
| `bcf3f8b` | 2026-11-03 14:05 | Run 20261103T215654Z_C2 (confirmatory, replicate 2) |
| `6f803d9` | 2026-11-03 14:12 | Run 20261103T220512Z_C1 (confirmatory, replicate 2) |
| `2d7bd57` | 2026-11-03 14:20 | Run 20261103T221238Z_C0 (confirmatory, replicate 2) |

## scoring

| Commit | Committed | Message |
| --- | --- | --- |
| `57d2d92` | 2026-10-16 12:42 | scoring: registry (31 rows), near_misses, check_registry, review notes (Step 3) |
| `a794dd0` | 2026-10-19 11:05 | Step 4a run 1: audit scripts and raw results |
| `54ff320` | 2026-10-19 11:11 | Step 4a run 2: isolation scoped to export, fuzzy cross-checked against seeds |
| `014523b` | 2026-10-19 11:18 | Step 4a: tighten 7 detection-key sets; add key-specificity check and before/after outputs |
| `813ea55` | 2026-10-19 11:23 | Add pre-rename generator originals (16 docs) for provenance |
| `fca09d8` | 2026-10-19 14:05 | Step 4b: blind realism reviews (Sonnet run kept, Opus run) of firm d97fd90 |
| `80ebd2e` | 2026-10-19 14:56 | Step 4: letters as carriers (also_in) for 8 client patterns; key-level fixes; near-miss updates |
| `98ff337` | 2026-10-19 15:26 | Step 5a: 24 probes (A-3, B-2, C-2), answer-key map, probe check |
| `345f7e2` | 2026-10-19 16:00 | check_isolation: skip .venv and caches, tolerate '~' tokens |
| `2630aae` | 2026-10-19 19:29 | Step 6a: judge and scorer (stub-tested) |
| `9989723` | 2026-10-19 21:01 | First live judge runs: C1, C2, C0 |
| `630aa4a` | 2026-10-19 21:15 | Post-run fixes: probe-only candidates, firm-reach store flags, same-quote annotation |
| `33988bb` | 2026-10-19 21:16 | Re-derive C1, C2, C0 scores with the post-run fixes (no model calls) |
| `a1cf687` | 2026-10-20 10:28 | Step 6b: judge validation set, labelling sheet, compare.py |
| `41889c6` | 2026-10-21 16:33 | Step 6b: labels |
| `77720ec` | 2026-10-21 16:52 | Step 6b: first judge validation run |
| `fb80178` | 2026-10-21 17:35 | Step 6b: adjudication of ordinary misses (11 cases) |
| `64c6056` | 2026-10-21 19:07 | Evaluation v2: family definitions (P1, P2, A1, A2), approved before any v2 number |
| `66f53f8` | 2026-10-21 19:12 | Evaluation v2: adjudication of six family-level cases |
| `1ba8081` | 2026-10-21 19:41 | compare.py: family rule and adjudicated-corrections figures (post-hoc), strict verdict unchanged |
| `93423da` | 2026-10-21 19:47 | Adjudication: V38 F03 ruling changed to No (bare mention of the note; judge right) |
| `47b1a8d` | 2026-10-28 10:12 | Judge prompt v2 (hash 0b5ea77dda85): rules for what counts as a verdict; --pre-rejudge guard |
| `a888d7a` | 2026-10-28 10:55 | Validation set v2 built (seed 20261028, 40 items W01-W40, answer key in validation/v2/construction), before labelling |
| `0053289` | 2026-10-28 15:51 | Validation v2 tooling: --set v2 run, family-level labelling page, unit-level compare mode |
| `9cba546` | 2026-10-30 14:11 | Validation v2: Alex's blind unit labels (labels_v2.csv), before comparison with the judge run or the answer key |
| `f0223e7` | 2026-10-30 14:30 | Validation v2: report (68%, FAIL) and Alex's post-hoc adjudication of 16 disputed units (37/40 post-hoc, not validation) |
| `9469ac8` | 2026-11-02 13:15 | Rejudge C1, C2, C0 under judge prompt v2 (hash 0b5ea77dda85); live_manifests keeps the latest judgment per run; xfail removed |
| `ddd9cc4` | 2026-11-02 13:28 | Judge the two N0 runs under judge prompt v2 (hash 0b5ea77dda85): no matter or client leaks; firm-reach patterns P1 and P2 in 9 of 48 outputs |
| `ec6c845` | 2026-11-03 10:34 | Pin determinism and hash tests to the runs the frozen validation sets were built from |
| `536ec28` | 2026-11-03 10:34 | Add confirmatory analysis script with prediction 7 and the prompt-hash gate |
| `d8454b8` | 2026-11-03 19:56 | Judge confirmatory replicate 1 under frozen v2 (0b5ea77dda85) with --repeat |
| `28463e9` | 2026-11-04 10:02 | Judge confirmatory replicate 2 under frozen v2 (0b5ea77dda85) with --repeat |
| `3542db7` | 2026-11-04 10:05 | Add confirmatory analysis config: eight judged runs, two replicates |
| `b383516` | 2026-11-04 10:17 | Confirmatory results: predictions 1 to 7 on eight judged runs (5 pass, 2 fail) |

Tags (each points at the commit shown):

| Tag | Commit |
| --- | --- |
| `scoring-conf-config` | `3542db7` |
| `scoring-conf-rep1` | `d8454b8` |
| `scoring-conf-rep2` | `28463e9` |
| `scoring-conf-results` | `b383516` |
| `scoring-confirmatory-script-v1` | `536ec28` |
| `scoring-eval-v1` | `fb80178` |
| `scoring-judge-v2` | `47b1a8d` |
| `scoring-lock-v1` | `80ebd2e` |
| `scoring-lock-v2` | `98ff337` |
| `scoring-n0-v2` | `ddd9cc4` |
| `scoring-rejudge-v2` | `9469ac8` |
| `scoring-validation-v2-labels` | `9cba546` |
| `scoring-validation-v2-result` | `f0223e7` |
| `scoring-validation-v2-set` | `a888d7a` |
| `scoring-validation-v2-tools` | `0053289` |

