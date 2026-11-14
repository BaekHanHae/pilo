# PILO-Skills AI Execution Gateway — integration boundary (draft)

Status: **Design candidate; not an approved executable capability**.
Target: PILO Core 0.3.1, SQLite schema 2.
Branch: `feature/pilo-skills-ai-gateway`.

## Existing behavior to preserve

- The existing `ExecutionMixin.register_skill` permits only reviewed built-in CODE skills.
- `create_plan` creates CODE steps; `scheduler_tick` invokes the fixed Python worker.
- The scheduler may retry timeouts. **Do not reuse this retry path for side-effecting AI CLI tasks.**
- Operator permissions, audit events, immutable plans, attempts, and lease fencing remain owned by Core.
- SQL migrations 0001 and 0002 must remain byte-identical.

## Proposed boundaries

1. The isolated `ai_execution_policy.py` module performs **structural checks only**. Its return value must never be treated as permission to spawn a CLI.
2. A future Core-owned authorization transaction must bind principal, project, immutable plan/step, adapter identity, effect class, scoped approval, checkpoint, and execution attempt.
3. Adapter execution must occur outside database transactions, in an explicitly selected project workspace with bounded environment, timeout, output size, and command allowlist.
4. The finalization transaction must validate the active attempt, fencing token, permissions, evidence references, and observed worktree effects.
5. A timeout, connection loss, or unknown filesystem/network side effect must become `UNCERTAIN` (or a separately approved equivalent durable state) and **must not auto-retry**.
6. Reconciliation requires operator review and durable evidence. Replay, rollback, and rebuild remain separate Core operations.
7. No CLI-specific session state is authoritative; cross-agent handoff manifests are untrusted inputs until Core verifies scope and evidence.

## Current implementation record

See [AI Gateway implementation status](ai_gateway_implementation_status.md) for
executed regression results, recovery transactions and conservative evidence gates.
This original proposal does not establish release readiness.

## Remaining integration work

- No new schema or migration.
- No scheduler integration.
- No production AI scheduler/approval integration.
- No process spawn or CLI discovery.
- No automatic startup reconciliation or worktree restoration.
- No end-to-end test.

## Verification

The isolated policy's seven unit tests were replicated and run under Python 3.13.5 in a temporary validation directory. This is **not** a test run from a full GitHub checkout. CI and full Core regression tests are pending.

## Proposed next implementation gate

Before enabling any external CLI, implement durable approval/scope checks and a separate AI attempt state machine with tests for cancellation, lease expiration, duplicate delivery, stale fencing, unknown effects, and explicit reconciliation. Keep the feature disabled by default.
