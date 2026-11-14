# PILO

**Local project context, preserved evidence, and recovery for AI coding workflows.**

[English](README.md) · [日本語](README.ja.md) · [한국어](README.ko.md)

PILO helps an AI coding assistant find project information and keep a record of exactly what it read. It brings project-scoped permissions, immutable context snapshots, and optional local analysis into one small Python application.

**Status:** 0.3.1 pre-release. Automated tests cover the bounded core workflows; this is not a production-readiness or universal retrieval-accuracy claim. [View CI results](https://github.com/BaekHanHae/pilo/actions/workflows/ci.yml).

## What you can do

- Index allowed UTF-8 backend/frontend text and search deterministically with SQLite.
- Preserve the returned context as a Snapshot with source hashes and current permission checks.
- Connect an MCP client through local standard input/output.
- Optionally use Ollama for semantic search and evidence-based analysis, and Graphify for Python structural relationships.
- Use operator-only APIs for reviewed CODE tasks and clean-Git checkpoints/recovery. These applying operations are disabled on the default MCP connection.

Example: index a repository, ask for checkpoint-related context, then read the same Snapshot later to verify the exact evidence used.

## Start in a few minutes

Requirements: Python 3.11+, Git, and SQLite 3.37+ with JSON functions and FTS5 trigram support. The implementation uses POSIX filesystem protection; use macOS or Linux. Remote CI covers macOS and Linux with Python 3.11/3.14. Windows is not supported by this candidate.

Get the source and enter its directory:

```sh
git clone https://github.com/BaekHanHae/pilo.git
cd pilo
```

Then run:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/pilo init --directory .pilo
.venv/bin/pilo --config .pilo/database_config.json add-project --key sample --name Sample --root examples/sample-project
.venv/bin/pilo --config .pilo/database_config.json search --project sample --query checkpoint
```

The final command returns context, its Snapshot ID, source paths, and a completion status. An empty or partial result is reported explicitly. Initialization refuses to overwrite an existing installation.

To index your own project, run `add-project` with its directory and a different project key. This is an explicit local operator action. It configures a dedicated reader and disables its temporary indexing identity afterward.

## Connect your coding assistant

Use the executable's absolute path to run `pilo --config /absolute/path/to/.pilo/database_config.json serve` as a local STDIO MCP server. The default connection exposes project listing/details, metadata-only evidence search, explicit bounded evidence export, and Snapshot reading; legacy context retrieval remains available. See the English [MCP specification](docs/mcp.md) for a configuration template and boundaries. Hosted/cloud clients cannot be assumed to access your local process.

## Optional features and limits

| Feature | Implementation | Current boundary |
|---|---|---|
| Semantic search | Local Ollama embeddings and exact cosine ranking | Up to 512 eligible units; computed on demand |
| AI analysis | Local Ollama over a preserved Snapshot | Structured answer and citation checks; model claims still need review |
| Graph relationships | Optional Graphify adapter | Python structure only, up to 100 files / 2 MB |
| Recovery | Clean-Git checkpoint, replay and rollback contracts | Git objects and content-store bytes must remain available |

The default installation requires no model, cloud account, API key, or Graphify. Read [optional extensions](docs/extensions.md) before enabling them. Models and third-party code are governed by their own licenses.

## Documentation

Formal specifications are maintained **in English only**:

- [Public implementation specification](docs/specification.md)
- [MCP contract](docs/mcp.md)
- [Optional extensions](docs/extensions.md)
- [Decisions and roadmap](docs/roadmap.md)
- [Testing and evidence](docs/verification.md)
- [Contributing](CONTRIBUTING.md), [security](SECURITY.md), [brand use](BRANDING.md)

The Japanese and Korean READMEs explain the product and quick start; they are not separate specifications.

## License

PILO-owned code and documentation are licensed under [MIT](LICENSE). Optional dependencies retain their own licenses, including Graphify's Apache-2.0 notices. See [third-party notices](THIRD_PARTY_NOTICES.md). No model weights, private project data, or original private conversations are distributed.

## Practical evaluation

The [PILO Practical Evaluation Report](docs/PILO_PRACTICAL_EVALUATION_REPORT.md)
compares standard and PILO-assisted Codex on a pinned learning-platform snapshot.
The initial pilot found equal task outcomes with higher token usage for the PILO
arm. Read-only snapshots remain a focused experiment; AI Gateway work is not a
prerequisite. The [local evaluation harness](tools/practical_eval/README.md) uses
Python and SQLite and does not add a dependency to the evaluated project.

The [retrieval recovery and held-out re-evaluation](docs/PILO_RETRIEVAL_REEVALUATION_REPORT.md)
restores release checks and improves file recall, but does not demonstrate repeatable
Codex productivity or uncached-token savings. Prefer explicit deterministic search
and small Snapshot export; automatic bulk context injection is not the default.
