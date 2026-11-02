# tuya-bulb-mcp

Local MCP server for Tuya / Smart Life Wi-Fi lighting. Connect an MCP-compatible AI client to a bulb directly over your local network with [TinyTuya](https://github.com/jasonacox/tinytuya). No Tuya Cloud calls are needed at runtime.

![Python](https://img.shields.io/badge/Python-3.10%2B-blue) [![License: MIT](https://img.shields.io/badge/License-MIT-blue)](LICENSE) ![MCP: stdio](https://img.shields.io/badge/MCP-stdio-blue)

## Features

- Local control with outgoing LAN connections; stdio communication with the MCP client.
- Four MCP tools for status, power, and colour/brightness/temperature.
- Bounded writes to supported datapoints DP20–24; no generic datapoint writer.
- Verified power writes and state-change verification via ACK or read-back.
- Idempotent requests return an already-set result without redundant writes.
- Interactive setup, read-only device compatibility verification, and a local baseline.

**Compatibility:** The DP20–24 mapping is designed for compatible Tuya bulbs using the light_ty firmware family. Other firmware mappings may require an adapted implementation.

## Requirements

- Python 3.10+ (3.11 recommended)
- Bulb paired in Smart Life / Tuya and accessible from this computer on the LAN
- Device ID, local IPv4 address, protocol version (3.3 or 3.4) and 16-character local key

The local key can be obtained through the [Tuya IoT Platform](https://iot.tuya.com) after creating a project and linking your Smart Life account. Cloud access may be required to obtain the key, but is not required for runtime control.

## Quick start

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

The scan is optional. If it finds nothing, run the wizard without --scan and enter the device details manually. Network isolation may prevent discovery.

The wizard:

1. Prompts for device details and a hidden local key.
2. Reads device status **without writing datapoints**, checking the DP20–24 mapping.
3. Captures the initial state and device identity into Git-ignored baseline_state.json if no baseline exists.
4. Saves the Git-ignored .env with an optional identity guard **only after successful verification**.

It does not overwrite an existing baseline. A different-device or legacy baseline without an identity must be backed up and manually removed before creating a new one. An incompatible or unreachable bulb leaves the previous .env unchanged. If the bulb is in scene/music mode, switch to white/colour in the app before setup. The --no-verify option bypasses verification and still saves configuration; do not use state-changing tools before confirming compatibility.

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

Use the venv bin/python on Linux/macOS. In Hermes, run /reload-mcp after changing config, and check with hermes mcp test tuya-bulb.

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

Replace example paths with your actual Python and server locations. Do not place device credentials in the client configuration.

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

The baseline restores the **first verified setup snapshot for the configured device**, not factory defaults. If absent, legacy, invalid or for another device, restoration fails without writing. The device firmware may switch to white mode after brightness/temperature updates, so the server orders writes for compatible firmware.

Verification uses ACK or fresh status where appropriate. An unverified write is reported as an error; no automatic recovery writes are sent. A failed sequence might have partially changed the device.

## Safety and troubleshooting

- Keep .env, baseline_state.json and scan/credential files out of Git.
- No arbitrary datapoint write tool is provided; only DP20–24 are written. DP25/26/34 are not modified.
- Device compatibility must be checked before writing; optional identity guard prevents misconfigured targets.
- If scanning fails, check Wi-Fi isolation and router device listings.
- If status fails, check the key, version, IP address and supported DP scheme.
- If baseline restore fails, complete read-only setup and verify the baseline identity. Back up and manually delete an old/unidentified snapshot before recapturing.
- Versions 3.3 and 3.4 are the validated configuration targets; other TinyTuya-supported versions require explicit compatibility work.
- On Windows, .env inherits its directory ACLs. Keep installation in a user-only folder and review permissions on shared machines.
- If tools are absent, check venv and client paths, MCP configuration and reload/restart.

Run offline regression checks with: python -m unittest discover -s tests -v

Hardware integration should be reviewed and tested separately before public release; offline regression tests use fake devices only.

## Project layout

- tuya_bulb_mcp_server.py — stdio MCP server
- setup_wizard.py — read-only setup and compatibility check
- baseline_state.example.json — sample snapshot format (not real device state)
- skills/tuya-bulb-mcp/SKILL.md — optional agent guidance
- AGENTS.md and CLAUDE.md — contributor safety instructions
- tests/ — offline regression tests

## Credits and license

[MIT](LICENSE) © 2026 Can Yurtaçan. Built on [TinyTuya](https://github.com/jasonacox/tinytuya) and the [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk).
