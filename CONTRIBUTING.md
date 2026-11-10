# Contributing

Use Python 3.11+ and a POSIX development environment. Create a virtual environment and install the package locally. Run `python -m unittest discover -s tests -v` before submitting a change.

Keep formal specifications, code comments and technical change descriptions in English. Maintain the same behavior, limits and quick-start commands in README.md, README.ja.md and README.ko.md. Introductory translations are welcome; do not create independently diverging specifications.

Changes to authorization, recovery, immutable records or migrations need meaningful failure-path tests. Do not rewrite applied migrations; use a reviewed additive migration and explicit upgrade plan. Do not add broad grants, arbitrary Skill entrypoints or hidden model/network calls.

Use synthetic examples only. Do not commit user databases, content-store bytes, private source snapshots, conversations, credentials, model weights or machine-specific configuration. Contributions intended for inclusion are submitted under this repository's MIT license; third-party code must retain its own license and attribution.
