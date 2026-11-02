# tuya-bulb-mcp

Local MCP server for Tuya / Smart Life Wi-Fi lighting. Connect an MCP-compatible AI client to a bulb directly over your local network with [TinyTuya](https://github.com/jasonacox/tinytuya). No Tuya Cloud calls are needed at runtime.

![Python](https://img.shields.io/badge/Python-3.10%2B-blue) [![License: MIT](https://img.shields.io/badge/License-MIT-blue)](LICENSE) ![MCP: stdio](https://img.shields.io/badge/MCP-stdio-blue) ![TinyTuya](https://img.shields.io/badge/TinyTuya-1.20-00A98F) ![Cloud](https://img.shields.io/badge/cloud-not%20required-success) ![Scope](https://img.shields.io/badge/scope-one%20device-orange) ![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey)

## Features

- Local control with outgoing LAN connections; stdio communication with the MCP client.
- Four MCP tools for status, power, and colour/brightness/temperature.
- Bounded writes to supported datapoints DP20–24; no generic datapoint writer.
- Verified power writes and state-change verification via ACK or read-back.
- Idempotent requests return an already-set result without redundant writes.
- Interactive setup, read-only device compatibility verification, and a local baseline.

**Compatibility:** This implementation is built for a single compatible Tuya `light_ty` bulb with the DP20–24 mapping. It is not a generic Tuya device controller. Firmware and datapoint layouts vary; read-only verification is required before any physical writes.

## Requirements

- Python 3.10+ (3.11 recommended)
- Bulb paired in Smart Life / Tuya and accessible from this computer on the LAN
- Device ID, local IPv4 address, protocol version (3.3 or 3.4) and 16-character local key

The local key can be obtained through the [Tuya IoT Platform](https://iot.tuya.com) after creating a project and linking your Smart Life account. Locate the bulb under the linked project's devices and retrieve its device ID and local key. The local IPv4 address and protocol version can be found through LAN discovery or your router. Tuya's cloud interface and credential retrieval requirements can change. Cloud access may be required to obtain the key, but is not required for runtime control.

**Before starting:** Keep the bulb powered and reachable on the same LAN, and have its device ID and 16-character local key available. Do not paste the key into chat, a GitHub issue or a client MCP configuration.

## Quick start

**First-time setup, in order:**

1. Pair your compatible bulb in the Smart Life / Tuya app and keep it reachable on the same LAN.
2. Obtain its **device ID and 16-character local key** from the linked [Tuya IoT project](https://iot.tuya.com). The optional LAN scan can help find its IP and protocol version.
3. Run the commands for your OS below. The setup wizard asks for the device details and verifies the bulb **read-only** before saving local configuration.
4. Add the MCP server to your AI client's configuration using the example in [MCP client integration](#mcp-client-integration), then connect or reload that client.
5. Ask the connected assistant for the bulb's status first; see [First-use examples](#first-use-examples).

**Windows (PowerShell):**

~~~powershell
git clone https://github.com/canyrtcn/tuya-bulb-mcp.git
cd tuya-bulb-mcp
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe setup_wizard.py --scan
~~~

**Linux / macOS:**

~~~bash
git clone https://github.com/canyrtcn/tuya-bulb-mcp.git
cd tuya-bulb-mcp
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python setup_wizard.py --scan
~~~

The scan is optional. If it finds nothing, run the wizard without `--scan` and enter the device details manually. Network isolation may prevent discovery. The wizard prompts for the local key securely when run interactively; it never needs the key as a command-line argument.

The wizard:

1. Prompts for device details and a hidden local key.
2. Reads device status **without writing datapoints**, checking the DP20–24 mapping.
3. Captures the initial state and device identity into Git-ignored baseline_state.json if no baseline exists.
4. Saves the Git-ignored .env with an optional identity guard **only after successful verification**.

It does not overwrite an existing baseline. A different-device or legacy baseline without an identity must be backed up and manually removed before creating a new one. To migrate a legacy baseline safely, rename `baseline_state.json` to `baseline_state.backup.json` in the local project directory, then run the wizard again with the same configured device; the new baseline will be captured from a fresh read-only status response. Both filenames are Git-ignored. Do not copy an old device's baseline into a new device installation. An incompatible or unreachable bulb leaves the previous .env unchanged. If the bulb is in scene/music mode, switch to white/colour in the app before setup. The --no-verify option bypasses verification and still saves configuration; do not use state-changing tools before confirming compatibility.

The network scan may create an ignored snapshot.json file. Avoid the separate TinyTuya wizard here because it can persist additional credentials in local files. Never share the local key in chat or version control.

### Configuration

| Variable | Description |
|---|---|
| TUYA_BULB_DEVICE_ID | Device identity |
| TUYA_BULB_IP | Local IPv4 address; a DHCP reservation is recommended |
| TUYA_BULB_VERSION | 3.3 or 3.4 |
| TUYA_BULB_LOCAL_KEY | Secret local device key |
| TUYA_BULB_EXPECTED_DEVICE_ID | Optional identity guard, enforced by the server |

Re-pairing or factory reset may rotate the key. When configuring a different bulb, review or delete the **local** baseline before capturing its initial state.

## MCP client integration

The MCP server uses JSON-RPC over stdio and does not listen for incoming HTTP traffic. TinyTuya makes **outgoing** LAN connections to the device (typically TCP 6668).

**Hermes Agent:** In the mcp_servers section of ~/.hermes/config.yaml, use paths appropriate for your installation:

~~~yaml
mcp_servers:
  tuya-bulb:
    command: "C:/path/to/tuya-bulb-mcp/.venv/Scripts/python.exe"
    args: ["C:/path/to/tuya-bulb-mcp/tuya_bulb_mcp_server.py"]
    timeout: 120
~~~

Use the venv `bin/python` on Linux/macOS. In Hermes, run `/reload-mcp` after changing config, and check with `hermes mcp test tuya-bulb`. Only edit or reload a client's configuration when you explicitly intend to change that installation; testing a separate checkout does not require editing an existing MCP registration.

**Claude Desktop or other stdio clients:**

~~~json
{
  "mcpServers": {
    "tuya-bulb": {
      "command": "C:/path/to/tuya-bulb-mcp/.venv/Scripts/python.exe",
      "args": ["C:/path/to/tuya-bulb-mcp/tuya_bulb_mcp_server.py"]
    }
  }
}
~~~

Replace example paths with your actual Python and server locations. Do not place device credentials in the client configuration. The optional [agent skill](skills/tuya-bulb-mcp/SKILL.md) helps compatible agents select tools directly, but is **not required** to use the MCP server.

### First-use examples

After your MCP client detects the four tools, try these requests **in the AI client chat** (not in PowerShell):

| What you say | What the MCP server does |
|---|---|
| "What's the current bulb status?" | Calls `get_status` (read-only) |
| "Turn on the bulb." / "Turn off the bulb." | Calls `turn_on` / `turn_off` |
| "Set the bulb to blue." | Uses `set_state(color="blue")` |
| "Set brightness to 40%." | Uses `set_state(brightness=40)` |
| "Set the colour temperature to 70%." | Uses `set_state(temperature=70)` |
| "Restore the saved baseline." | Uses `set_state(preset="baseline")` |

The baseline is the first verified setup snapshot, **not** a factory reset; restoring it can change the light. The specific AI client decides how to translate chat requests into MCP tool calls.

## Tools

| Tool | Purpose |
|---|---|
| get_status() | Read power, mode, brightness, temperature, colour and raw datapoints |
| turn_on() / turn_off() | Change DP20 only when necessary and verify the power state |
| set_state(...) | Set mode, colour, HSV values, white brightness, temperature or restore baseline |

State parameters:

| Parameter | Supported values |
|---|---|
| mode | white or colour |
| color | red, orange, yellow, green, cyan, blue, purple, pink or white |
| hue | 0–360 |
| saturation, value | 0–100% |
| brightness | 1–100% |
| temperature | 0–100% (warm to cool) |
| preset | baseline |

Examples: set_state(color="blue"), set_state(brightness=40), set_state(preset="baseline").

The baseline restores the **first verified setup snapshot for the configured device**, not factory defaults. If absent, legacy, invalid or for another device, restoration fails without writing. The device firmware may switch to white mode after brightness/temperature updates, so the server orders writes for compatible firmware. If the device is in scene/music mode, `set_state(mode="white")` or `set_state(mode="colour")` can exit it; colour/brightness/temperature changes are deferred until the device has exited that mode. The baseline preset may exit scene/music only when no DP22/23/24 changes are needed.

Brightness and temperature requests use whole-number percentages mapped to DP22/23 in steps of 10; a raw value such as 475 cannot be requested directly through the percentage API. The captured baseline stores and restores raw datapoints without rounding.

Verification uses ACK or fresh status where appropriate. An unverified write is reported as an error; no automatic recovery writes are sent. A failed sequence might have partially changed the device.

## Safety and troubleshooting

- Keep `.env`, `baseline_state.json`, and scan/credential files out of Git. The `.gitignore` also covers dated scan dumps and `baseline_state.backup.json`, but ignore rules do not protect against explicitly forced commits; inspect `git status` before publishing.
- Never paste a device local key into public bug reports or screenshots. If a key is exposed, rotate it through the device's supported pairing flow.
- No arbitrary datapoint write tool is provided; only DP20–24 are written. DP25/26/34 are not modified.
- Device compatibility must be checked before writing; optional identity guard prevents misconfigured targets.
- If scanning fails, check Wi-Fi isolation and router device listings.
- If status fails, check the key, version, IP address and supported DP scheme.
- If baseline restore fails, complete read-only setup and verify the baseline identity. Back up and manually delete an old/unidentified snapshot before recapturing.
- Versions 3.3 and 3.4 are the validated configuration targets; other TinyTuya-supported versions require explicit compatibility work.
- On Windows, .env inherits its directory ACLs. Keep installation in a user-only folder and review permissions on shared machines.
- If tools are absent, check venv and client paths, MCP configuration and reload/restart.

### Offline tests (no physical bulb required)

After installing dependencies into the virtual environment, run:

**Windows:**

~~~powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
~~~

**Linux / macOS:**

~~~bash
.venv/bin/python -m unittest discover -s tests -v
~~~

These tests use simulated devices and do not control a real bulb. The [CI workflow](https://github.com/canyrtcn/tuya-bulb-mcp/actions) runs them on Windows and Ubuntu using Python 3.10 and 3.12. Passing offline tests does not guarantee compatibility with every bulb; perform a controlled, read-only device check before any hardware writes.

## Project layout

- tuya_bulb_mcp_server.py — stdio MCP server
- setup_wizard.py — read-only setup and compatibility check
- tuya_config.py — shared, minimal `.env` parser
- baseline_state.example.json — sample snapshot format (not real device state)
- skills/tuya-bulb-mcp/SKILL.md — optional agent guidance
- AGENTS.md and CLAUDE.md — contributor safety instructions
- tests/ — offline regression tests

## Credits and license

[MIT](LICENSE) © 2026 Can Yurtaçan. Built on [TinyTuya](https://github.com/jasonacox/tinytuya) and the [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk).
