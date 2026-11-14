# Practical evaluation harness

A dependency-free Python/SQLite evaluation driver using the existing PILO Core.
It does not launch agents, activate the AI Gateway, alter source repositories,
or apply schema 3. Run from the PILO repository root with Python 3.11+.

## Private artifacts

Use an ignored directory outside the indexed source corpus. Corpus, task gold,
Context Snapshot bodies, raw agent logs and proposed patches can contain private
source. Never commit or upload them to public CI. Output directories are exclusive;
existing results are preserved instead of overwritten. Use a separate output path
for another experiment. `aggregate()` emits metrics without source paths/text.

## Reproduce retrieval

Freeze committed, clean tracked source with `harness.freeze(source, new_corpus)`.
It reads Git objects and returns a source SHA, per-file hashes and manifest digest.
The allowlist excludes data, dotfiles and real config; this is not a secret scanner.
Review selected committed content before sending it to an external agent.

Prepare a private JSON array of tasks:

```json
[
  {
    "id": "T01",
    "question": "Where is this behavior implemented?",
    "query": "searchTerm",
    "gold": {"relative/source.py": "exact predeclared evidence anchor"}
  }
]
```

Gold must exist in the frozen corpus. It is used only for grading, never as a
separate answer key in agent prompts. Document how tasks and queries were selected.

```sh
python3 -m tools.practical_eval.harness \
  --corpus /absolute/private/corpus \
  --tasks /absolute/private/tasks.json \
  --output /absolute/private/new-results \
  --budget 8192
```

The budget is UTF-8 bytes, not measured model tokens. The literal control emits
matching lines; PILO uses its existing default scanner, lexical ranker and chunks.
Do not silently change file coverage, ranking or task gold to improve the score.
The driver creates disposable schema-2 state, disables the setup indexer, uses a
project-scoped reader, validates snapshot replay and checks selected bytes against
source/hash evidence. Reads of the source are read-only; local PILO metadata is
necessarily written to store snapshots and audit events.

The SQLite database contains `run`, `retrieval`, `agent` and `repair_validation` tables. Missing token
usage stays NULL; it must not be reported as zero. The aggregate summary contains
file-level recall/precision/MRR, latency, context bytes and errors. Snapshot replay
of empty content is not retrieval success. For exact-anchor coverage, compare each
gold anchor with contexts.private.json and report the number of nonempty contexts.

## Prepare external Codex comparison

`protocol.prepare_sessions(corpus, tasks, contexts, new_directory, repairs=...)`
creates two identical source copies, prompts and an output schema. The second arm
receives PILO context; the first does not. Repair tasks are evaluator-authored
instructions with independent test oracles. The initial pilot used a predecessor
wording of the same protocol; its exact executed prompts are retained and hashed.

Run both arms sequentially using the same installed Codex version, authenticated
account, model/config and available tools. Counterbalance order in later trials.
The initial pilot intentionally retained CLI defaults and did not capture a resolved
model ID; do not infer verified model equivalence from the same command alone.
No execution approval for PILO is implied by running a separately authorized Codex
comparison. An example for an explicitly authorized read-only session is:

```sh
codex exec --ignore-user-config --ephemeral --sandbox read-only \
  --skip-git-repo-check --cd /absolute/private/session-copy --json \
  --output-schema /absolute/private/answer-schema.json \
  --output-last-message /absolute/private/answer.json - \
  < /absolute/private/prompt.txt > /absolute/private/events.jsonl
```

The harness itself never runs that command. Do not add a fallback model or
automatically retry a failed/incomplete session. Record failure and missing metrics.
Use `agents.import_session(...)` to validate exact answer evidence and import actual
turn.completed token counters. Capture-window duration uses log birth/modification
timestamps on macOS; it is a wall-time proxy, not CPU or per-task timing.

`agents.apply_patch_copy(...)` accepts exact unique old/new replacements only for
reviewed paths, and writes only a new experimental copy. Apply each repair to an
independent copy. Run identical existing and driver-authored regression tests for
both arms under the caller's normal test sandbox; never evaluate generated code
against real libraries, credentials or production databases. Use `agents.import_test_log(...)` to preserve actual pytest summary counts and
log hashes, including full-suite failures and missing summaries. A targeted pass is not
a full-suite pass. Retain test output, return codes, patches and source hashes.

## Verification

```sh
python3 -m unittest discover -s tests -p 'test_practical*' -v
python3 -m unittest discover -s tests -v
python3 tools/validate_schema.py --report /tmp/pilo-practical-sql.json
```

Tests use synthetic public fixtures with real Core/SQLite snapshot transactions.
They verify frontend coverage gaps, replay, budgets, binary-cache exclusion, exact
evidence and traversal checks, missing usage, scoped patch copies and prompt gold
separation. They do not require the learning-platform repository, Codex credentials,
network, vector models or private raw artifacts.
