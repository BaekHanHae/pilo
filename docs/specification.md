# PILO public implementation specification

Version: 0.3.1 pre-release. Language: English only.

This is the public contract for the code in this repository. Internal historical specifications and private design conversations are not distributed. Their version numbers do not represent this package's release number.

## State and provenance

SQLite schema version 2 is authoritative for logical state. SQL migrations 0001 and 0002 are immutable; package copies must match the repository originals byte for byte. Initialization applies 0001 and explicitly upgrades to 0002 with a backup. Opening an existing database never silently migrates it. Unknown schema shapes, history or checksums fail closed.

Immutable content bytes reside in a content-addressed store. References use SHA-256. Publish bytes durably before committing database references. Retain Git objects and CAS bytes with database backups; a database-only backup is insufficient for full recovery. Automatic garbage collection is disabled.

## Authorization and spaces

A local operator provisions explicit permissions. No implicit wildcard grant exists. MCP identity comes from trusted server configuration, not tool arguments. PROJECT and COMMON spaces are distinct. Reads, cached context, preserved snapshots, resources and graph output are checked against current permissions. Approval-sensitive operations use separate authorization and approval checks.

`add-project` is a local operator command. It registers an existing directory, grants project.read/context.read to a dedicated principal, scans with a temporary files.scan identity, then disables that identity. It configures a four-tool read connection. It does not enable applying operations.

## Ingestion and retrieval

Scan only allowed UTF-8 file types. Enforce containment with descriptor-relative no-follow reads, skip symlinks, hidden/runtime/dependency directories, enforce source size/file caps and conservatively exclude secret-shaped content. Exclusion is not a comprehensive secret scanner.

Current eligible FileRevision and approved knowledge versions form the query corpus. FTS5 trigram and short literal matching provide lexical search. Semantic search is optional. RULE/DECISION context is mandatory and fails explicitly if it cannot fit. max_tokens is a conservative UTF-8 byte upper bound, not a model-specific tokenizer count.

Snapshots preserve assembled content, source hashes, budget metadata and a sealed item set. Reads recheck current source-space access. Query caches are scoped to authorization, policy and source generations. Partial/empty results are explicit; no answer correctness guarantee follows from a complete retrieval status.

## Execution and recovery

CODE skills are limited to the reviewed text.hash, text.count and context.echo registry. Manifest/worker hashes, immutable plans, DAG cycle rejection, attempt history, timeout/retry bounds and lease fencing prevent unchecked arbitrary entrypoints and stale results. The worker is single-slot; the MCP request dispatcher may serve bounded concurrent requests.

Checkpoints require a clean Git worktree. Rollback, recorded-context replay and index rebuild are separate operations. Recovery approval, locks and reconciliation are domain-specific. Historical records are preserved rather than rewinding the database. Untracked/dirty-worktree restoration, full machine-loss recovery and arbitrary shell skills are not implemented contracts.

## Observability and extensions

Diagnostics use predefined profiles; ErrorVault stores redacted occurrences and resolution records. Model usage can be tied to preserved context. Local AI/semantic/graph adapters are specified in extensions.md. Their output remains evidence-linked but not automatically approved knowledge.

## Release boundaries

POSIX filesystem features are required. This release is tested on macOS/Linux with Python 3.11/3.14. Windows, HTTP/OAuth transport, unrestricted AI/HYBRID scheduling, persistent approximate vector indexing, media semantic graph extraction and production load certification are outside this release.
