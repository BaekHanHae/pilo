# Deterministic Review Gates (proposed, inactive)

Status: design-only policy candidate. This document adds no runtime feature, execution authority, automatic model invocation, migration, or default configuration change. It builds on the read-only retrieval and immutable Snapshot contract in [retrieval-evidence-contract.md](retrieval-evidence-contract.md). It is informed by change-scoped review and evidence-validation patterns, without incorporating an external review engine.

## Three governing principles

1. **Deterministic First.** Before any optional AI call, a trusted local process determines the authorized project scope, Git baseline and changed paths, excluded paths and reasons, relevant source handles, byte budget, and a bounded estimated invocation count. If the scope cannot be established, stop rather than silently widening it.
2. **Evidence Before Inference.** Verify machine-checkable assertions with deterministic code: source existence, canonical path and project boundary, source/selected-unit hash, source offset and line span, Git revision, test command exit status and output provenance. An LLM may interpret intent or suggest a hypothesis but cannot mark an unverified assertion as a verified fact. A hash proves integrity, not semantic correctness.
3. **Measured Expansion Only.** An additional AI stage is opt-in and disabled by default. Enable it only after a recorded, controlled comparison shows repeatable benefit on task outcomes or evidence quality, with acceptable uncached input tokens, elapsed time, false positives and maintenance overhead. A passing CI pipeline or improved retrieval recall alone is not evidence of developer productivity gains.

## Proposed preflight preview (no model call)

A future caller may generate a read-only preview using existing Git metadata, allowed-source scanner, permission checks and metadata-only search; do not add a second indexer. The preview should include:

- project identity, authorized root and scope, base/head Git revision or a declared non-Git source generation;
- changed, eligible and excluded files, with a specific reason for each exclusion (for example outside scope, symlink, secret pattern, binary, size limit, untracked or unavailable);
- relevant source handles and deterministic selection order, rule/policy version and a bounded byte budget;
- number of planned optional model calls and an **estimate**, clearly distinguished from measured token consumption and monetary cost;
- explicit unknowns: uncommitted changes, missing baselines, unsupported file types, stale source handles and incomplete test coverage.

A preview is a planning artifact, not permission to read disallowed files or proof that selected files contain every relevant defect. No model call or source modification occurs during preflight. If the current source or authorization changes between preview and export, revalidate; do not trust a stale preview.

## Proposed claim and audit record

A reviewer finding is a *claim*, not verified knowledge. Where applicable, record:

- claim identifier, project/scope, originating tool and policy version;
- exact source path, revision, source hash, unit hash, line/character range, and Snapshot reference when exported;
- claim text, classification (**EXTRACTED** vs **INFERRED**), verification status (**UNVERIFIED**, **DETERMINISTICALLY_VERIFIED**, **HUMAN_REVIEWED**, or **REJECTED**), verifier and time;
- checks performed and their observed results (test command, exit code, log reference/hash), including checks not run and why;
- optional model identifier/settings, actual measured input/cache/output tokens and wall time if available; never substitute estimates for measurements.

A valid path/hash/line range validates the citation target, not the truth of a semantic claim. A passing test validates only its declared assertions. Keep original evidence immutable; corrections append new decisions rather than rewriting historical evidence. Private source bodies and prompts must not be published in public reports.

## Promotion and rollback gate

Before activating any new AI review stage, pre-register tasks and evaluation criteria; compare against the current deterministic-search/explicit-Snapshot baseline under equivalent permissions, source revisions, prompts and model settings. Include failures, excluded runs, false positives, uncached tokens, wall time and setup cost. Repeat with held-out tasks and counterbalanced order. If the stage fails to show repeatable net benefit, keep it off and preserve the minimal baseline.

## Current implementation boundary

- **Already present:** bounded authorized source scanning; deterministic lexical ranking; metadata-only search; explicit evidence export; immutable Snapshot replay and source/hash verification; audit-related metadata.
- **Not claimed as implemented by this document:** a Git-diff preview command, a new claim-state database schema, automatic review, automatic cost estimation, AI critique/reflection, or a production review engine.
- **Explicitly deferred:** AI Gateway, schema-3 activation, vector infrastructure, background orchestration and automatic context injection.

This policy is documentation for future review decisions only. Do not treat it as a passing test or as authorization to merge prior Draft PRs.
