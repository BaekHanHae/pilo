# Verification policy

The private 0.3.0 development run reported 73 application tests and 143 historical SQL cases passing in Python 3.15.2/SQLite 3.54.1 and Python 3.14.8/SQLite 3.53.1 on macOS. Those historical private reports and data are not shipped as public fixtures. The 143-case SQL runner is distributed under tools/ and uses only synthetic fixtures.

This candidate generates a fresh schema-1 fixture directly from immutable SQL and upgrades it in temporary directories. No personal database, backup, source checkout, absolute user path or service credential is required. The fresh distribution/setup tests exercise CLI initialization, project registration, read-only grants, temporary-indexer disabling, search, and packaged SQL parity.

Run from the source tree:

```sh
python3 tools/validate_schema.py
python3 -m unittest discover -s tests -v
```

The Graphify integration case skips explicitly if its optional environment is unavailable. Model unit cases use controlled responses; they are not evidence of live model quality. The private integration evaluation additionally exercised real Ollama calls, official MCP SDK calls, Codex tool discovery/resource reads, and OpenCode legacy/modern handshake/catalog compatibility. OpenCode agent task execution was not verified.

GitHub Actions runs SQL cases, core tests, a clean-source checkout evaluation and a wheel quick start across macOS/Linux with Python 3.11/3.14. Check the [actual workflow results](https://github.com/BaekHanHae/pilo/actions/workflows/ci.yml) for the commit/tag you use. Optional Graphify tests skip when its separate environment is absent.

Package checks should verify no private data, runtime environments or model weights are included; both SQL copies match; links resolve; language READMEs use the same commands; and English formal documentation remains a single contract. A local report is generated during release preparation outside this repository.

## Source-checkout evaluation

With a clean Git checkout and PILO installed, run `python tools/evaluate_checkout.py --report build/ci-results/project-evaluation.json`. It tests eight source-oriented lexical queries and exact Snapshot rereads, creates/verifies a clean-Git checkpoint, and runs three diagnostic profiles using disposable state. It does not mutate or roll back the source repository. Generated build/distribution/environment directories are excluded from ingestion. This bounded self-project evaluation is not a general retrieval benchmark.
