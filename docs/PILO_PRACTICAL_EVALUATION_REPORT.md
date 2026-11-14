# PILO Practical Evaluation Report

Date: 2026-11-14. Status: initial paired pilot, not a release or production approval.

## Decision

This experiment did **not demonstrate better development outcomes from PILO**.
Standard Codex and PILO-assisted Codex both supplied valid evidence for 20/20
investigation tasks and proposed repairs that passed the same two targeted test
suites. PILO-assisted Codex used 68.79% more reported input tokens, 27.21% more
uncached input tokens, and a 4.45% longer log capture window in this single batch.
These are observations, not statistically established causal effects.

PILO's read-only snapshots have measurable evidence-reuse value: all 20 snapshot
replays were byte-identical, and supplied context contained the task's exact gold
anchor in 9/20 tasks versus 5/20 for a small literal-line search control. However,
relevant-file recall was lower (45% versus 60%), and default ingestion omitted
frontend source formats. Continue only a small, focused retrieval/snapshot pilot;
the measured benefit does not justify prioritizing the AI Gateway or schema 3.

## Repository and baseline verification

- PILO main runtime: `10c97f23bf2d60784aed19a19ea02982b6fff408`. The evaluation
  branch starts here, independently of the AI Gateway Draft PR stack.
- Draft PRs #1, #2, #6, #7 and #8 were inspected and remain open and unmerged.
  Issues #3–#5 remain open. Recovery/provenance/rehearsal improvements in the stack
  do not enable production execution. Startup recovery delivery, a separate
  scheduler, OS/network/process isolation, approved write-output verification,
  production migration recovery and real adapter E2E remain gates.
- The related repository was verified as `BaekHanHae/study-platform`, a private
  repository whose default branch is `master`, not `main`. Its local development
  checkout is one commit ahead of remote master. Both exact SHAs are retained in
  the private provenance manifest; the evaluation pins the local committed state.
- Before evaluation changes, PILO main ran 77 tests: 76 passed and one skipped.
  The learning-platform snapshot ran 69 tests: 65 passed, four failed. Three
  failures involved the FTS5 search path; one involved native OCR availability.
  Its existing lint check reported four errors. These failures are baseline
  observations, not caused by adding PILO. Documentation lag was also observed.
- Source snapshots contain 46 allowlisted committed text files. Local data,
  textbooks, databases, environment files, real configuration and credentials
  were excluded. No learning-platform source branch or production data changed.

The source manifest fingerprint is
`c8e9b07391edc93e487be2638eb4d906b35aa56e5a34e5f5fe4518e5adb9f56a`.
The machine-readable summary is authoritative if that fingerprint is updated.

## Method

The initial dataset has **20 development investigation tasks plus two repair
pilots**, not 20 independent coding trials. Tasks cover search, citations, provider
permission/budget/cost records, JSON parsing, ingestion resume, embedding identity,
mastery, watcher lifecycle, OCR, chunking, frontend reader/upload and configuration.
A maintainer inspected the snapshot and selected exact source anchors before the
agent sessions. The tasks are representative but author-selected and not blinded.
Gold paths/anchors are never included as grading data in the agent prompts.

1. Copy committed source through Git objects into a disposable private corpus;
   preserve source hashes and leave the original checkout independently usable.
2. Initialize ordinary schema-2 PILO state outside the corpus. Existing setup
   temporarily provisions an indexer, disables it after scanning and provisions a
   project-scoped reader with only project.read/context.read. Source access is
   read-only; retrieval appends snapshots/audit metadata in disposable PILO state.
3. Run the same 20 query hints against the literal-line control and existing
   Workspace.retrieve, using an 8,192 **UTF-8 byte** context budget. No ranker,
   ingestion defaults or historical migrations were changed for the benchmark.
4. Launch two fresh external Codex CLI sessions sequentially: standard first,
   then PILO-assisted. Both receive identical source copies, questions, repair
   instructions, output schema and read-only inspection tools. Only the second
   receives the retrieved PILO snapshots. Neither session runs tests or edits
   files. The driver applies each returned patch to an independent fresh copy
   and runs actual existing plus driver-authored regression tests there.
5. Validate quotes against exact source bytes, score predeclared anchors, and
   import actual CLI token usage into SQLite. Preserve raw events/prompts/answers
   locally with artifact hashes; publish only aggregates and anonymized task IDs.

Codex CLI version: 0.169.0. Both sessions used the same unmodified CLI defaults,
`--ignore-user-config --ephemeral --sandbox read-only --skip-git-repo-check`, and
a structured final-output schema. Resolved model identity was not emitted in the
captured events, so exact model equivalence is **unverified**. No model override,
Gateway dispatch, feature activation or automatic agent retry was used.

## Measured results

### Retrieval and evidence

The literal control is a deterministic exact substring scan returning matching
lines; it is **not** a replacement for the standard Codex session. PILO returns
larger indexed chunks. Their different snippet sizes limit efficiency comparisons.
Relevance is graded at file level against the supplied gold set, not by an LLM.

| Metric | Literal-line control | PILO main |
|---|---:|---:|
| Queries | 20 | 20 |
| Relevant-file recall | 60% | 45% |
| Mean file precision | 38.33% | 33.33% |
| Mean reciprocal rank | 0.4571 | 0.3833 |
| Context includes exact gold anchor | 5/20 | 9/20 |
| Nonempty contexts | 12/20 | 11/20 |
| Mean query time | 3.82 ms | 9.20 ms |
| Total returned context bytes | 7,098 | 56,271 |
| Retrieval exceptions | 0 | 0 |
| Snapshot byte-identical replay | N/A | 20/20 |

All selected PILO chunks in the 11 nonempty contexts matched both their content
hash and source text. Nine empty snapshots also replayed correctly; empty replay
must not be counted as useful retrieval. File identity alone does not establish
that a particular excerpt answers the question. Gold-anchor checks address part
of that gap, but are still syntactic proxies.

Initial setup took 0.147 seconds and indexed 33/46 corpus files. The omitted 13
files were outside the existing scanner's file-pattern coverage; frontend formats
were an actual evaluation blind spot. No source-content exclusions were reported
by the scanner within its supported file types. Missing context was a retrieval
quality failure, even when no exception occurred.

### Actual paired Codex sessions

| Metric | Standard Codex | PILO-assisted Codex |
|---|---:|---:|
| Exact source quotes valid | 20/20 | 20/20 |
| Relevant file + complete gold anchor | 20/20 | 20/20 |
| Repair pilots passing targeted checks | 2/2 | 2/2 |
| Combined full suite including driver checks | 73 passed, 1 failed | 73 passed, 1 failed |
| Completed read-only shell commands | 4 | 6 |
| Reported input tokens | 132,280 | 223,277 |
| Reported cached input tokens | 91,392 | 171,264 |
| Input minus cached input tokens | 40,888 | 52,013 |
| Reported output tokens | 2,906 | 3,186 |
| JSONL log capture window | 74.64 s | 77.96 s |

Token counters come from each CLI turn.completed event, not a tokenizer guess or
PILO's byte-budget field. They include cumulative input across tool interactions.
Actual currency cost is unknown; a ChatGPT-authenticated CLI session does not
provide a reliable per-token dollar charge. Capture-window time runs from log-file
creation to its final write, excludes result import/testing, and is not precise
CPU time or per-task latency. PILO setup/retrieval time is additional overhead.

### Repair pilots

- D1: repair invalid FTS5 matching and preserve short CJK literal retrieval in the
  hybrid path. Both independently generated patches passed **22 targeted tests**,
  including existing search/API checks and three additional regression checks.
- D2: add deterministic polling-cycle handling for PDF additions, modifications
  and deletions without repeated unchanged-file callbacks. Both patches passed
  **seven targeted tests**, including existing watcher checks and two additional
  lifecycle checks. The event-driven backend was preserved.

Applying both repairs together in fresh copies and running all existing tests plus
the five driver checks yielded **73 passed, one failed** for each arm. The remaining
failure was the same pre-existing native OCR case; neither arm achieved a fully
green platform suite. The learning repository itself was left unchanged.

These are substantive changes to real development defects, applied only in
experimental copies. Neither patch was merged or deployed. Passing targeted tests
does not mean the entire platform baseline is healthy; the unrelated native OCR
failure remains. This is two repair pilots, not evidence of sustained maintenance
or production correctness. Driver checks were identical for both arms and were
written by the evaluator, not by either evaluated agent; they were not blinded.

## What to keep, improve, defer or remove

| Function or investment | Recommendation and evidence |
|---|---|
| Read-only Context Snapshot/CAS provenance | Keep for handoff and reproducible evidence: 20/20 replay, source/hash checks on all selected chunks. Test long-term handoff value separately. |
| Default source ingestion | Improve file-pattern coverage first. Frontend files were missing despite being directly relevant to real tasks. Keep project scope and exclusions explicit. |
| Lexical query interpretation and packing | Improve against the frozen tasks. Concept phrases frequently produced empty context; file recall trailed a trivial search control. Do not tune only to these 20 anchors. |
| Automatic large snapshot injection | Avoid as the default. This batch achieved equal task outcomes with more input tokens and more inspection commands. Prefer on-demand, small, cited excerpts. |
| Ambiguous token accounting | Replace token-savings claims derived from UTF-8 bytes with explicit byte budgets plus actual CLI counters. Byte counts are not measured model token usage. |
| Graph/vector/agent orchestration and schema 3 | Defer expansion. None was necessary for this pilot, and no measured development benefit justifies added integration cost yet. Preserve isolated Draft work without activating it. |
| Independent project usability | Preserve. No platform dependency on PILO, server, background process or data migration was added. |

Continued PILO development is justified **conditionally for a small read-only
retrieval/evidence workflow**, not as a proven productivity platform. Keep the next
investment bounded: expand safe source coverage, improve query handling and offer
on-demand excerpts; then rerun a new held-out task set with independently repeated,
counterbalanced sessions and verified model identity. Require either better repair
success or lower uncached token/time cost at equal success before broad expansion.
If that gate is not met, replace automatic context assembly with ordinary search
plus a minimal snapshot/citation exporter.

## Harness verification

After implementation, the PILO suite ran 85 tests: 84 passed and one skipped.
Eight new evaluator tests use real Core/SQLite and synthetic source fixtures.
SQL validation ran 143 tests successfully, with integrity OK and no foreign-key
errors. CI explicitly uses Bash pipefail for the unittest/tee step so a failed
suite cannot be hidden by successful log capture. Exact commit/CI results are
recorded in the Draft PR; pending checks are not counted as passed.

## Reproduction and limitations

See [evaluation harness instructions](../tools/practical_eval/README.md) and
[the public aggregate evidence](evaluations/practical-study-platform-summary.json).
Private manifests, corpus, prompts, raw CLI events, returned patches, test logs and
SQLite results remain under the ignored local build/practical directory. They
are not uploaded to public CI artifacts. Public regression tests use synthetic
fixtures and real PILO Core/SQLite, with no private project dependency.

An early harness preflight accidentally treated generated bytecode as text in the
literal control. That invalid run was retained privately and excluded from the
reported comparison. The corrected run uses a clean committed corpus and ignores
binary/cache files; a regression test covers it. No agent session was rerun to
select a better result.

The experiment has one fixed-order paired batch, no randomization, no blinded
semantic assessment, only two repair trials, existing platform baseline failures,
unknown resolved model identity and no production or long-term outcome measure.
Twenty questions within one session are correlated observations. The report does
not establish statistical significance, general Codex superiority/inferiority,
security gate completion or a production-ready integration.
