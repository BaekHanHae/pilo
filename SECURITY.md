# Security

PILO is a local pre-release application. Use a dedicated data directory and explicit project-scoped identities. A read-only MCP tool can still create internal Snapshot, audit and usage records. Do not expose the trusted operator CLI as an MCP tool.

Please do not include credentials, private source excerpts or real databases in a public issue. Use [GitHub private vulnerability reporting](https://github.com/BaekHanHae/pilo/security/advisories/new) for security-sensitive reports. Reproduce with synthetic data whenever possible and avoid public disclosure of exploitable details.

The filesystem allow list and conservative secret-pattern exclusions are not a comprehensive secret detector. Model evidence is untrusted input; generated claims require review. Keep database, content-store and Git backups together, and test restore procedures separately.
