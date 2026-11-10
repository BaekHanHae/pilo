# Verification policy

The private 0.3.0 development run reported 73 application tests and 143 historical SQL cases passing in Python 3.15.2/SQLite 3.54.1 and Python 3.14.8/SQLite 3.53.1 on macOS. Those historical private reports and data are not shipped as public fixtures. The 143-case SQL runner is distributed under tools/ and uses only synthetic fixtures.

This candidate generates a fresh schema-1 fixture directly from immutable SQL and upgrades it in temporary directories. No personal database, backup, source checkout, absolute user path or service credential is required. The fresh distribution/setup tests exercise CLI initialization, project registration, read-only grants, temporary-indexer disabling, search, and packaged SQL parity.

Run from the source tree:

```sh
python3 tools/validate_schema.py
python3 -m unittest discover -s tests -v
```

The Graphify integration case skips explicitly if its optional environment is unavailable. Model unit cases use controlled responses; they are not evidence of live model quality. The private integration evaluation additionally exercised real Ollama calls, official MCP SDK calls, Codex tool discovery/resource reads, and OpenCode legacy/modern handshake/catalog compatibility. OpenCode agent task execution was not verified.

GitHub Actions runs core tests across macOS and Linux/Python versions and verifies a clean wheel quick start. Its results are pending until the repository exists and the workflow actually runs. No badge claiming a passing remote run is displayed.

Package checks should verify no private data, runtime environments or model weights are included; both SQL copies match; links resolve; language READMEs use the same commands; and English formal documentation remains a single contract. A local report is generated during release preparation outside this repository.
