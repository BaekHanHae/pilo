# Deterministic retrieval and on-demand evidence

This is a schema-2, local, read-only source workflow. It neither enables the AI
Gateway nor grants execution authority. Historical migrations are unchanged.

## Reproduced failure

On PR #9 head 901c26cd1ba08c52e0fdb9b68bbf636e9f880e39, the unchanged checkout
evaluator misses docs/specification.md for Snapshot. The target's two candidate
units rank 21 and 22 and are excluded by the 32,768-byte budget. One report consumes
14,003 source bytes before the target is considered. The old ranker gives matching
units nearly identical relevance and then sorts by path and random unit ID. A
single source can consume multiple slots before another source gets any evidence.
The first-100 candidate cut also obscures recall and can discard mandatory rules.

No checkout assertions, queries or expected source paths are changed by the fix.
The previous report and public measurements remain historical evidence.

## Safe source coverage

The existing text scanner additionally permits .ts, .tsx, .js, .jsx, .css, .html
and .svg. These files are treated as text, never executed or rendered. Existing
UTF-8, regular-file, size, file-count, secret-pattern and symlink checks still
apply. Existing dot-directory, dependency and build-output exclusions remain.
This is conservative ingestion, not a guarantee that arbitrary committed source
is free of secrets. Review the source allowlist before exporting private evidence.

## Lexical policy

The versioned lexical-evidence-v2 policy is deterministic and dependency-free:

1. Normalize Unicode/case, split identifier words, and use at most sixteen distinct
   meaningful terms. Multiword queries can match noncontiguous terms. Punctuation
   is data and is never interpolated into a full-text query expression.
2. Rank mandatory RULE/DECISION units first, then explicit path matches, term
   coverage, phrase match, source role and bounded occurrence density. Reference
   documentation outranks reports/tests on relevance ties. This role is a search
   hint, never a trust or authorization label; no query or target file is allowlisted.
3. Break ties by source path, original unit ordinal and content hash, never UUID.
   Include every relevant candidate rather than silently truncating to 100 units.
4. Pack all mandatory units first, then one optional unit per source, then deferred
   units in ranked order until the caller's byte budget is exhausted. Full required
   rules must fit or the transaction fails; source diversity never drops a rule.
5. Cache keys include the ranker version, authorization scope, policy and source
   generations. Prior snapshots remain readable under current permissions. Reusing
   an execution idempotency key across changed ranking contracts fails visibly.

This is bounded by the existing small local corpus limits, not a large search
service. Do not add a vector database or model dependency to solve this problem.
Semantic tools remain opt-in and are not needed or activated by this workflow.

## On-demand APIs

`search_evidence(actor, project, query, limit=5)` is a read-only database operation.
It returns only source names, unit handles, ordinals, unit hashes and full source
hashes. It neither includes source bodies nor creates a Snapshot. Empty results
must be disclosed rather than interpreted as evidence that a behavior is absent.

`get_evidence(actor, project, unit_ids, query, max_bytes=2048)` accepts one to eight
explicit handles and a 256–8192 UTF-8 byte budget. Handles must still belong to
currently eligible, authorized sources; stale/cross-project handles are rejected.
It selects contiguous query-focused excerpts (normally at most 768 bytes per
optional unit) using coverage, density and stable offsets. It returns an immutable
Snapshot and the source/unit hashes and character ranges needed to verify excerpts.
A short excerpt is not proof that an entire function or task has been understood.
Mandatory rules are included in full even on this explicit path or fail the budget.

Both byte counts and separators/headers are accounted for. Byte ranges are never
split inside a UTF-8 character. Legacy retrieve/max_tokens remains compatible;
its budget has always been UTF-8 bytes, not measured model input tokens. New
responses state context_bytes and budget_unit explicitly.

Snapshot replay checks the sealed body hash, item/unit hash, referenced historical
source CAS hash and exact source slice for every selected unit. Source updates do
not rewrite history. Revoked scope or corrupt historical source bytes block replay.
No changes to Snapshot tables or immutable triggers are required.

## CLI and MCP

```sh
pilo --config /private/state/database_config.json evidence-search \
  --project sample --query 'provider configuration' --limit 3
pilo --config /private/state/database_config.json evidence \
  --project sample --query 'provider configuration' --unit-id SELECTED_HANDLE \
  --max-bytes 2048
```

Fresh setup enables pilo_search_evidence and pilo_get_evidence alongside existing
reader tools. MCP's start-task prompt and the practical session builder now advise
on-demand search/export, not bulk prefetch. CLI search and pilo_get_context are
retained for explicit legacy callers. The session builder requires legacy-bulk mode
to recreate historical injection; no default prompt contains prefetched source.
Existing installations/configurations are not silently rewritten.

MCP tool identity is fixed by trusted configuration. Retrieval can append private
Snapshot/audit metadata while remaining read-only with respect to project source.
The re-evaluation exposes only reader tools through a disposable stdio server;
no process scheduler, write tool, local model or AI Gateway is enabled.
