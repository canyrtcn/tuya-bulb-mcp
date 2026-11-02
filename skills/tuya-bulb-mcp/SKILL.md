---
name: tuya-bulb-mcp
description: "Use when controlling a Tuya/Smart Life bulb via the tuya-bulb-mcp MCP tools. Direct tool calls only — no terminal detours."
version: 1.0.0
author: tuya-bulb-mcp
license: MIT
metadata:
  hermes:
    tags: [tuya, smart-life, bulb, mcp, smart-home, iot]
    related_skills: []
---

# Tuya bulb MCP — direct tool usage

`tuya-bulb-mcp` is a local stdio MCP server that controls ONE Tuya / Smart Life Wi-Fi bulb over the LAN (TinyTuya, no cloud at runtime). This skill describes how an agent should USE it.

## FAST PATH — direct MCP tools first

Simple bulb commands must use the existing direct MCP tools immediately.

For power commands:

- `turn_on`
- `turn_off`

For state/color/brightness/temperature/baseline commands:

- `set_state`

If a matching direct MCP tool exists:

- DO NOT use tool_search
- DO NOT inspect the project
- DO NOT read implementation files
- DO NOT use terminal
- DO NOT create scripts
- DO NOT edit the skill during the request
- DO NOT perform redundant verification
- DO NOT search for alternative implementations

Call the direct tool immediately.

Only enter terminal/debug/fallback flow if the direct MCP call actually fails or the requested capability genuinely does not exist.

## Tools

| Tool | Behaviour |
|---|---|
| `get_status()` | Read-only summary: `power`, `mode`, `brightness` (DP22), `color_temperature` (DP23), `color` (`raw` + decoded HSV), `raw_dps`. |
| `turn_on()` / `turn_off()` | Write DP20 only if required, and verify via status read-back. |
| `set_state(mode?, color?, hue?, saturation?, value?, brightness?, temperature?, preset?)` | Idempotent state change. Returns `already_set` (no write) when nothing changes. `preset="baseline"` restores the captured baseline. |

Result shape: `{success, changed, verified?, reason?, verification?, dps_written?, state?}`.

## Safety rules (non-negotiable)

- One device only — the target comes from `.env`. No device-id parameters, no generic datapoint tools.
- Writes are limited to DP20–24 (`20` power, `21` work_mode, `22` bright_value, `23` temp_value, `24` colour_data). **Never write DP25 / DP26 / DP34.**
- The local key lives ONLY in `.env` (gitignored). Never print it, log it, or commit it. Never create `tinytuya.json` / `devices.json` (they persist secrets).
- Verify writes: power actions use status read-back, while state changes use matching ACK or status read-back. Do not retry blindly.
- Do not use `python -m tinytuya wizard` for key retrieval — fetch the local key from the Tuya IoT Cloud device details instead.

## Pitfalls

- **DP schemes differ per firmware.** The server is built for the `light_ty` (20–26) family. If `get_status` returns a different layout (e.g. the common 1–5 scheme), adjust the DP map in the server deliberately and re-verify read-only before any write.
- **Brightness/temperature writes switch the bulb to `white` mode.** Writing DP22/23 auto-changes `work_mode`; a mixed single packet ends `white`. `set_state` orders writes (white-ops first, colour-ops last with a `21='colour'` re-assert), so colour/baseline targets land correctly.
- **Multi-DP ACKs are partial** (often only the first dp is echoed). Never treat a partial ACK alone as failure — rely on the tool's read-back verification.
- **Local key rotates** on re-pairing or factory reset; re-fetch it from the cloud.
- **IP changes** break local control until re-scanned — set a DHCP reservation on your router.
- `get_status` is always read-only. When in doubt, read first. Baseline restore requires a local snapshot tied to the configured device ID and can change the device; it is not a read-only smoke test.

## Setup / wiring (only if asked)

See `README.md` (setup commands for Windows/Linux/macOS, MCP client config) and `AGENTS.md` (step-by-step agent instructions). The CLI wizard `setup_wizard.py` creates the `.env` and performs a read-only verification.
