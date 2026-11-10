# Decisions and roadmap

Formal specifications are English-only. README.md, README.ja.md and README.ko.md provide parallel public explanations and identical quick-start commands.

## Accepted public decisions

- Local-first SQLite logical state, content-addressed immutable evidence, Git code history.
- Authorization and space isolation at the Core boundary; no implicit MCP identity grant.
- CODE-first execution; optional local model analysis is an explicit separate endpoint.
- Preserve historical snapshots and keep rollback, replay and index rebuild distinct.
- MIT for PILO-owned code; retain third-party licenses and model terms separately.
- PILO is the umbrella project name. Additional modules should share permissions and provenance contracts instead of duplicating state stores. Module/product names are proposals until actually shipped.

## Before the first public release

1. Exercise the wheel and quick start outside the source directory, with synthetic state only.
2. Validate source privacy, license notices, README parity and links.
3. Require remote CI to pass for the exact released commit.
4. Complete a broader real-project evaluation and document supported platforms and known failures.
5. Publish an explicitly bounded pre-release under the confirmed owner account. Name/trademark clearance is a separate brand-development task; no registered trademark or exclusive-name claim is made.

## After the first public release

Prioritize install/update ergonomics, useful examples, recovery drills and client-specific compatibility reports. Measure actual semantic retrieval quality and latency before persistent vector indexes. Evaluate AI/HYBRID scheduling, other languages/media, parallel workers and dirty-worktree preservation independently. Do not describe roadmap items as implemented features.
