# PILO Retrieval Recovery and Practical Re-evaluation

Date: 2026-11-14. This follows Draft PR #9. Its original report, public summary and
private raw evidence are preserved unchanged. No source learning-project branch,
production data, historical migration, AI Gateway or schema-3 activation changed.

## Decision

**Do not expand automatic context retrieval. Prefer the minimal deterministic
search and explicit Snapshot exporter implemented here.** Retrieval quality and
release reliability improved, but repeatable practical benefit was not demonstrated.
The optional-PILO arm used 33.52% more uncached input tokens in the valid comparison,
with equal exact-evidence scores and equal strict repair success. The agents never
called the optional reader tools in those valid sessions. Therefore neither timing
nor repair differences can be attributed to consuming PILO evidence.

Keep the new on-demand APIs available for explicit evidence/handoff needs. Do not
add automatic bulk injection, background orchestration, vector infrastructure or
execution capabilities on the strength of this experiment. A small exporter is
justified by reproducible source/hash verification; automatic development assistance
still fails the practical decision gate.

## Failure reproduction and cause

The unchanged checkout evaluator failed at PR #9 head
`901c26cd1ba08c52e0fdb9b68bbf636e9f880e39`: the Snapshot query returned content but
omitted docs/specification.md. The target units were candidates 21 and 22; both
were excluded by the 32,768-byte assembly budget. A single report consumed 14,003
source bytes before those units were considered. There were 56 candidates.

The old relevance keys mostly reduced matching units to alphabetical source order,
then random unit IDs. Multiple chunks from one source could exhaust the budget.
The first-100 cut could also discard useful or mandatory units as a corpus grew.
No evaluator assertion, query, expected source, historical source corpus or previous
measurement was removed to get a passing result.

## Implemented recovery

Implementation commit: `b6fe7cb2c44c72ffb792f46b18af696a99623fb8`.

- Add .ts/.tsx/.js/.jsx/.css/.html/.svg as text under existing UTF-8, regular-file,
  symlink, secret-pattern, size, dependency/build exclusion and file-count checks.
- Rank Unicode/identifier query terms deterministically using path match, coverage,
  phrase, source role and bounded density; resolve ties with ordinal/hash, not UUID.
  Source-role hints confer no authority and do not whitelist benchmark targets.
- Select all mandatory units, one optional unit per source, then deferred units
  under a byte budget. Full mandatory rules must fit or fail; no hidden top-100 cut.
- Version candidate caches. Preserve immutable Snapshots and verify selected unit
  hashes, historical source CAS hashes and exact source slices on replay.
- Offer metadata-only search followed by explicitly selected, bounded excerpts
  through CLI/MCP. No source body is injected by the session builder's default.
  Legacy full retrieval and explicit legacy-bulk experiment mode remain compatible.

See [the evidence contract](retrieval-evidence-contract.md). The implementation
uses existing SQLite storage and Python only; no new runtime/model dependency.

## Held-out retrieval evaluation

Twenty new questions were declared before model sessions: ten identifier/path-like
hints and ten natural-language hints. They differ from the original twenty tasks,
but use the same pinned private development snapshot. They are author-selected,
not a blind or exhaustive benchmark. Gold paths/anchors are grading inputs, not
answer keys supplied to agents. The frozen held-out manifest SHA256 is
`6c1456822da4972f4ada6c3c7f596ec2e881ffc4cdf1315e6cd8fb828730e678`.

Compare prior runtime versus recovered runtime at the same 8,192-byte budget.
A separate compact profile requests the first two search handles with a 2,048-byte
export budget; it is not a simulation of the model's actual tool choices.

| Metric | PR #9 full retrieval | Recovered full retrieval | Compact explicit export |
|---|---:|---:|---:|
| Indexed corpus files | 33/46 | 46/46 | 46/46 |
| Relevant-file recall | 30% | 95% | 95% |
| Gold anchor included | 6/20 | 16/20 | 11/20 |
| Mean reciprocal rank | 0.2167 | 0.8000 | N/A |
| Total source-context bytes | 33,902 | 153,783 | 36,553 |
| Snapshot replay | 20/20 | 20/20 | 20/20 |
| Retrieval exceptions | 0 | 0 | 0 |

Metadata-only recovered search has relevant-file recall of 65% at rank 1, 95% at
rank 3 and 100% at rank 5. Small automatic top-one selection is still unreliable.
Compact exported bodies are 76.23% smaller than recovered bulk bodies, but also
contain fewer exact anchors. Search metadata adds 26,854 bytes across these twenty
requests; the body-only reduction is not a model-token saving or full MCP wire-size
measurement. The prior runtime's smaller output partly reflects missed evidence.

Mean local query times were approximately 8.87 ms prior, 10.76 ms recovered full,
and 11.87 ms for metadata search plus compact export. File precision remains a
limited proxy: the gold sets specify acceptable files rather than every relevant
file. A complete source hash proves integrity, not relevance or truth.

Three independent fresh recovered state installations produced byte-identical full
contexts for all twenty queries and the same 95% file recall/MRR 0.8. This demonstrates
ranking/packing stability under new IDs. It does not establish repeated coding gains.

## Counterbalanced Codex comparison

Two blocks of ten questions and one repair each were run in this order:

1. A standard, then A optional-PILO.
2. B optional-PILO, then B standard.

All four initial prompts contain zero prefetched source bodies. Within each pair,
prompt bytes, output schema, source hashes and read-only shell permissions are
identical. Only the optional-PILO sessions expose a disposable reader-only STDIO
MCP server; ordinary source inspection remains available. No scheduler, source-write
or local generation tool is exposed. Source copies were verified unchanged afterward.

Codex 0.169.0 used explicit `--model gpt-6.1-sol` and
`model_reasoning_effort="low"`, with no fallback. The requested model alias and effort
are pinned; an immutable backend weight revision is not exposed by the CLI. Fresh
ephemeral read-only sessions use monotonic process wall timing and actual CLI usage,
not the original pilot's log-timestamp proxy. Plan SHA256:
`9f9365c1bf5949639984fa972809c9a563c2b869348ced7150f238a05f173a93`.

| Metric | Standard | Optional on-demand PILO |
|---|---:|---:|
| Valid source quotes / gold anchors | 20/20 | 20/20 |
| Strict repair successes | 1/2 | 1/2 |
| Input tokens | 146,727 | 166,262 |
| Cached input tokens | 88,064 | 87,936 |
| Uncached input tokens | 58,663 | 78,326 |
| Output tokens | 4,153 | 3,881 |
| Total process wall seconds | 108.07 | 105.32 |
| Read-only shell commands | 6 | 7 |
| MCP tool calls | 0 | 0 |

Input rose 13.31%; uncached input rose 33.52%. Aggregate wall time fell 2.54%, but
A became slower (59.43 → 65.27 s) and B faster (48.64 → 40.05 s). This is not a
repeatable efficiency improvement, especially because B's PILO repair was not
applicable. CLI tool availability, stochastic read choices and cache state can
change costs even when no evidence tool is called. No causal attribution or
currency-cost claim is made.

### Repair and environment details

R1 hardened negative/non-finite/non-numeric monetary inputs and spending bounds.
Both applied patches passed **34 tests** (19 new contract checks plus 15 existing
quiz checks). An initial oracle wrongly required ValueError/TypeError where the
stated task only required rejection. It was corrected uniformly to also accept
the existing BudgetError domain exception; the original strict log and both oracle
hashes are retained. Agents were not rerun to improve their repairs.

R2 required case-insensitive PDF handling in native and polling watcher paths.
The standard patch applied and passed all four new deterministic checks, but the
combined targeted run was **eight passed, one failed** in an existing native
callback/timing test. The optional-PILO patch proposed an old block occurring
three times; the existing unique-replacement driver rejected it. Its code tests
were **not executed**. This is an application-format failure, not proof that the
proposed algorithm is wrong. The driver limitation applies equally to both arms.

For native-path coverage, existing declared dev dependency watchdog 6.0.0 was
installed only into an isolated evaluation folder. The original project and its
venv were not modified. The unmodified baseline's native watcher suite subsequently
terminated with exit 133 and no complete summary; this environment is not a clean
native baseline. Do not label the single callback failure a proven repair regression
or claim a green learning-platform suite. The stricter end-to-end success definition
counts only a unique applied patch with all targeted checks passing: one per arm.

### Invalid preflight retained

Before the valid plan, a shared instruction ambiguously prohibited execution tools,
which blocked standard shell reads while still allowing MCP reads. Those two
sessions are excluded from effectiveness results and retained as invalid preflight.
They consumed 357,127 input tokens, 90,759 uncached input tokens and 111.09 seconds.
This is real evaluation/setup overhead, reported separately rather than hidden.
A new equal-permission plan was registered; no external side-effecting application
execution was retried. These protocol/oracle/environment issues limit confidence in
a small initial experiment and should be fixed before any larger study.

## Release validation and boundaries

At implementation commit b6fe7cb:

- Unit suite: **102 executed, 101 passed, one skipped**. Seventeen added recovery
  tests exercise real Core/SQLite, growth, file recall, budgets, UTF-8 offsets,
  permissions/stale handles, immutable records, source corruption, caches and CLI/MCP.
- SQL: **143 passed**, integrity OK, no foreign-key errors; migrations unchanged.
- Unchanged checkout evaluation: **8/8**, checkpoint verified, three diagnostic
  profiles passed, Core healthy.
- Wheel built and installed outside the source checkout; frontend indexing,
  bounded export, Snapshot replay and doctor checks passed using the installed package.
- [Actions run 43592362589](https://github.com/BaekHanHae/pilo/actions/runs/43592362589)
  passed all four Ubuntu/macOS × Python 3.11/3.14 jobs, including wheel/install smoke.

The strengthened growth fixture puts large reports alphabetically before a reference
and exceeds the old 100-unit prefix. Final report/corpus expansion is rechecked at
the follow-up head; exact final commit and CI results are recorded in Draft PR #10.
A passing release pipeline does not grant merge or execution authorization.

## Evidence and next boundary

[Machine-readable summary](evaluations/retrieval-recovery-summary.json) publishes
aggregates and artifact hashes only. Private source, gold, plans, raw agent events,
patches, SQLite records and test/crash logs remain in ignored build/recovery. The
original PR #9 report/summary and build/practical artifacts remain historical.

Two counterbalanced blocks are not independent repeated repairs on the same task.
No agent used the optional service during the valid comparison, exact-anchor scores
are syntactic, native-backend validation is unstable, and maintenance hours were not
measured. Retrieval is improved; overall practical development efficiency is not.
Retain explicit search/export and fix usability or evidence-selection needs only
when a real user needs them. Do not expand automatic context assembly until new,
cleanly controlled trials show repeatable practical benefit at acceptable overhead.
