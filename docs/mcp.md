# Local MCP contract

The server uses newline-delimited JSON-RPC over STDIO. It supports legacy 2025-06-18 and 2025-11-25 initialization plus the reviewed 2026-07-28 per-request metadata path. Modern catalogs return private cache scope and zero TTL. Unknown legacy revisions are offered a supported revision; unsupported modern revisions are rejected.

Only protocol messages go to stdout. Caller arguments cannot override identity, executable, model or endpoint. Tool schemas reject unknown fields. Redacted domain errors are separate from protocol errors. The server-side mcp_enabled_tools list restricts both discovery and calls. Applying tools additionally require mcp_allow_writes=true, and still require domain permissions.

## Default setup

After init and add-project, the server exposes:

| Tool | Purpose |
|---|---|
| pilo_list_projects | List projects readable by the configured identity |
| pilo_get_project | Read one authorized project |
| pilo_get_context | Legacy explicit context retrieval; not default prefetch |
| pilo_search_evidence | Find source/hash handles without source bodies |
| pilo_get_evidence | Export selected bounded excerpts as an immutable Snapshot |
| pilo_get_snapshot | Read a preserved Snapshot under current permissions |

Example client configuration; replace the executable and config placeholders with your own absolute paths:

```json
{
  "mcpServers": {
    "pilo": {
      "command": "/absolute/path/to/.venv/bin/pilo",
      "args": ["--config", "/absolute/path/to/.pilo/database_config.json", "serve"]
    }
  }
}
```

This is a generic STDIO JSON example, not a claim that every client uses the same configuration format. Codex stores server configuration in TOML:

```toml
[mcp_servers.pilo]
command = "/absolute/path/to/.venv/bin/pilo"
args = ["--config", "/absolute/path/to/.pilo/database_config.json", "serve"]
enabled_tools = ["pilo_list_projects", "pilo_get_project", "pilo_search_evidence", "pilo_get_evidence", "pilo_get_snapshot"]
tool_timeout_sec = 180
```

Reconnect the client after changing code, server identity or its tool catalog. A separate diagnostic client's success does not prove that an already-open chat refreshed. Hosted clients require separate local-access support. No network listener is installed by PILO.

## Extension tools

Explicitly enable pilo_semantic_context, pilo_analyze_snapshot and pilo_graph_project only after configuring the corresponding local adapter and project-scoped permissions. Both client and server allow lists must include them. The new endpoints do not enable source modification or recovery application. See extensions.md.

The start-task prompt recommends on-demand evidence. Search only when needed,
select handles, and request small excerpts; do not inject every task context into
an initial prompt. Source hashes and character ranges can be verified against the
preserved historical source. See [the evidence contract](retrieval-evidence-contract.md).
Retrieval may append private audit/Snapshot metadata while remaining read-only
with respect to the project. No AI Gateway or schema-3 activation is implied.
