# Pilot contract: matter-boundary experiment

All data are synthetic. No real clients, employers, courts, judges, cases or privileged material. Every entity is invented.

## Folders
These are siblings under legal-ai-pilot/. Each is its own git repo.
- firm/ holds generated documents only: no code, no answer key.
- pipeline/ holds code, gates, stores and run outputs. It reads ../firm and never writes to it.
- scoring/ holds the registry (answer key), scorers, the judge and the validation set. It may read ../firm and ../pipeline/runs. Nothing in pipeline/ may read scoring/.

## Access rules
1. A session started in pipeline/ must not open, list, search or reference anything in ../scoring.
2. Only scorers read registry.jsonl. No gate or downstream agent may read it.
3. Every model call from pipeline code goes through pipeline/src/llm.py, which appends one line per call to the run's usage.jsonl.
4. Conditions, model names, temperature and prompts live in config files and are copied into each run folder.
5. Matter notes are generated once and reused by all conditions.
6. firm/ is edited only by the generator (Step 2) and the seeder (Step 3). After the registry is locked it is frozen.
7. No API keys or paid services. Never set, read or ask for ANTHROPIC_API_KEY.
8. Config names a backend (claude_cli or codex_cli) and a model per role (agent, gate, judge). Pipeline logic must not depend on features specific to one backend (skills, subagents, slash commands). Prompts are plain files.
9. AGENTS.md mirrors this file for Codex. Regenerate it from CLAUDE.md; never edit it independently.
10. Agents and pipeline runs read the firm only through a clean export (git archive of the locked tag, no .git). They never read the firm repository or its history.

## Schemas (one JSON object per line)
- Registry row: id, client, matter, type (verbatim, paraphrase, client_pattern, area_pattern), text, detection_keys, intended_reach (matter, client, firm), doc_path.
- Artifact metadata: artifact_id, store, client, eligibility_tags, creating_stage. It carries no source matter.
- Ledger row: artifact_id, source_matter, gate, condition, timestamp. Source matter lives only here.
- Probe row: id, new_matter, type (topical, fishing, cross_scope), text.
- Score row: run_id, condition, tap, reader, registry_id, status (absent, paraphrased, verbatim), method (deterministic, judge, human).
- Usage row: run_id, timestamp, stage, condition, model, input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, latency_ms.

## File locations
- scoring/registry.jsonl
- pipeline/data/probes.jsonl (probe text only, no registry ids)
- pipeline/runs/<run_id>/ holds stores/, ledger.jsonl, probe_outputs.jsonl, usage.jsonl and a copy of the config
- scoring/scores/<run_id>/scores.jsonl

## Working rules for every session
- Do only what the current prompt asks, and only inside the folder it names.
- Write checks for what you build, run them, and report the results.
- Say plainly what you could not verify.
- If a requirement is ambiguous, stop and ask. Do not guess.
- Do not run git commit. The user makes checkpoints.
- Keep replies short: counts and file paths, not summaries of what you wrote.