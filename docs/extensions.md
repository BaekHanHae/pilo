# Optional local extensions

These are explicit opt-in adapters. The base package does not download models, install Graphify, change another application's configuration, or start Ollama.

## Ollama

Run a separately installed local Ollama server at 127.0.0.1:11434. Install local models appropriate to your machine and their license terms. The tested model tags are gemma3:4b and embeddinggemma:300m; tags can change, so record the actual model digests when evaluating a release. No weights are redistributed here.

Add an extensions object to your private instance's database_config.json:

```json
{
  "extensions": {
    "enabled": true,
    "generation_model": "gemma3:4b",
    "embedding_model": "embeddinggemma:300m",
    "graphify_python": "/absolute/path/to/the/python/with/graphify"
  }
}
```

Merge this object into the generated config; do not replace the database/migration fields. Use local model aliases only. The fixed local HTTP endpoint, disabled proxies and denied redirects do not authorize configuring an Ollama cloud/remote model alias.

A local operator grants vector.read for semantic search, ai.run and model.record for analysis, or graph.read for Graphify. Existing project.read/context.read grants remain necessary. Use the exact project_id printed by add-project:

```sh
pilo --config /path/to/database_config.json grant --principal pilo-reader --project PROJECT_ID --permissions vector.read,ai.run,model.record,graph.read
```

Extend mcp_enabled_tools in the same private config to include the desired extension tools, retain mcp_allow_writes=false, and update the client's allow list. Restart the connection. Do not grant unused permissions in a shared deployment.

## Semantic context

pilo_semantic_context embeds only currently eligible authorized units and ranks by exact cosine similarity. Reject nonfinite, zero-length, wrong-count or inconsistent-dimension embeddings. There is a 512-unit corpus limit and a 100-candidate limit; larger corpora fail visibly. Embeddings are computed on demand, without a persistent vector index. Assembly reuses mandatory rules, current authorization and immutable Snapshot sealing. Quality must be measured on the intended corpus.

## Local analysis

pilo_analyze_snapshot requires a matching project Snapshot and a non-empty evidence body up to 16,000 bytes. It requests at most 512 generated tokens, enforces an answer/citations JSON structure, rejects invented source paths and incomplete/truncated output, then rechecks permissions. Artifacts and model usage are preserved. Output is UNREVIEWED_MODEL_OUTPUT: matching citation paths is not proof of the answer's claims. A zero local API fee excludes hardware, electricity and elapsed-time cost. This endpoint is not a scheduler AI/HYBRID executor.

## Graphify

Install the separately licensed optional package in an isolated environment and use its interpreter's absolute path:

```sh
python3 -m venv .graphify-venv
.graphify-venv/bin/python -m pip install graphifyy==0.9.105
```

The reviewed integration targeted Graphify 0.9.105 at upstream commit 5eedffa87476a063a05bed96f17275ed63f05c1a. Verify a newly resolved package and dependencies before treating it as the same environment; the package index distribution is not asserted byte-identical to that source checkout.

The adapter stages only accepted immutable Python FileRevision bytes, uses structural extraction without an LLM/parallel extraction, and attaches revision/hash evidence to output. Caps: 100 files, 2 MB input, 60 seconds, 8 MB captured JSON. It rechecks revisions/permissions before publishing. Returned output is capped at 30 matching nodes and 60 adjacent edges; the complete graph has a CAS reference. Structural relationships are not semantic truth. No vendor source or graph environment is included in this repository.
