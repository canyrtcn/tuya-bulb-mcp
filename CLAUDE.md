# CLAUDE.md

This repository's agent instructions live in **AGENTS.md** — read it first:

- `AGENTS.md` (setup for Windows/Linux/macOS, tool contract, safety rules)

Non-negotiables in one line: local key stays in `.env` only (never print/commit),
one device only, writes limited to DP20–24 (never DP25/26/34), verify writes with
ACK matching or status read-back, match saved baseline to device identity; do not use `tinytuya wizard` in this project's flow.
