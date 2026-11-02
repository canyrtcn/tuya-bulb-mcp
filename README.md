# tuya-bulb-mcp

**Local MCP server for a single Tuya / Smart Life Wi-Fi bulb.** Talks to the device directly over your LAN — no cloud at runtime, no Home Assistant, no third-party Tuya MCP package.

Give any MCP-capable AI agent the ability to ask *"is the light on?"* and actually get an answer from the hardware.

<p>
  <img alt="Python" src="https://img.shields.io/badge/python-3.10%2B-3776AB?logo=python&logoColor=white">
  <img alt="License" src="https://img.shields.io/badge/license-MIT-blue">
  <img alt="MCP" src="https://img.shields.io/badge/MCP-stdio-6E56CF">
  <img alt="TinyTuya" src="https://img.shields.io/badge/TinyTuya-1.20-00A98F">
  <img alt="Cloud" src="https://img.shields.io/badge/cloud-not%20required-success">
  <img alt="Scope" src="https://img.shields.io/badge/scope-one%20device-orange">
  <img alt="Platform" src="https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey">
</p>

---

## What is MCP?

The **Model Context Protocol** is an open standard that lets an AI application call external tools in a structured way. Instead of the model guessing what your light is doing, it calls a tool that asks the light.

```
┌──────────────────┐   JSON-RPC over stdio   ┌───────────────────┐   TCP 6668   ┌──────────┐
│    AI agent      │ ◄─────────────────────► │  this MCP server  │ ◄──────────► │   bulb   │
│  (Hermes, etc.)  │      (local pipe)       │     (TinyTuya)    │    (LAN)     │          │
└──────────────────┘                         └───────────────────┘              └──────────┘
```

- **stdio transport** — the client spawns this server as a child process and speaks over stdin/stdout. No ports are opened, nothing is exposed to the network.
- **Stateless per call** — each tool call connects to the bulb, does one thing, returns JSON, disconnects.
- **Bounded surface** — four tools, hard-wired to one device ID. There is no "write any datapoint" escape hatch.

Never wired an MCP server before? The client needs one config block (below) and the agent gains the tools at startup. That's the whole integration.

---

## Features

| | |
|---|---|
| 🔌 **Direct LAN control** | Talks to the bulb over TCP 6668 with [TinyTuya](https://github.com/jasonacox/tinytuya) — no Tuya Cloud dependency after setup |
| 🎯 **Single device** | Scoped to one device ID from `.env`; no device-selection parameter, no generic datapoint writer |
| ✅ **Verified writes** | Every write is confirmed by the device ACK or a read-back — never a silent "sent" |
| ♻️ **Idempotent** | Asking for a state the bulb is already in writes nothing and returns `already_set` |
| 🧠 **Device quirks handled** | Brightness/temperature writes flip this bulb family to `white` mode; the server orders datapoints so colour and baseline targets land correctly |
| 🔐 **Secret hygiene** | Local key lives only in `.env`; scrubbed from every log, error and tool result |
| 🚫 **Safe by default** | Writes limited to DP20–24; DP25/26/34 are never touched |

---

## Requirements

- Python **3.10+** (3.11 recommended)
- Bulb already paired in the Smart Life / Tuya app, on the **same LAN** as the machine running the server
- One-time access to the [Tuya IoT Platform](https://iot.tuya.com) to read the device's local key

---

## Quick start

```bash
git clone https://github.com/canyrtcn/tuya-bulb-mcp.git
cd tuya-bulb-mcp
```

### Windows (PowerShell)

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
.\.venv\Scripts\python.exe setup_wizard.py --scan
```

### Linux / macOS

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python setup_wizard.py --scan
```

The wizard:

1. optionally scans your LAN for Tuya devices (device ID, IP, protocol version),
2. prompts for the four values — the local key input is hidden,
3. writes `.env` (mode `600` where supported),
4. finishes with a **read-only** `status()` call. No writes.

Expected output:

```
[OK] Device responded — power=on  mode=colour  DP22=500  DP23=475
     (read-only check — nothing was written)
```

If that passes, the server is ready to register with your MCP client.

> **Scan finds nothing?** Some networks block local broadcast (AP/client isolation, VLANs). Read the IP from your router's client list and the device ID from the Tuya IoT console — the wizard accepts both manually.

---

## Configuration

`.env` is gitignored — never commit it.

| Variable | Required | Description |
|---|---|---|
| `TUYA_BULB_DEVICE_ID` | ✅ | Device ID from the LAN scan |
| `TUYA_BULB_IP` | ✅ | LAN IP. Set a **DHCP reservation** so it doesn't move. |
| `TUYA_BULB_VERSION` | ✅ | Protocol version from the scan — `3.3` or `3.4` |
| `TUYA_BULB_LOCAL_KEY` | ✅ | 16-character key from the Tuya IoT console |
| `TUYA_BULB_EXPECTED_DEVICE_ID` | — | Hard guard: the server refuses to start unless the configured device ID matches this value |

### Where the values come from

**Device ID / IP / version** — LAN scan:

```bash
python -m tinytuya scan 25 -nocolor -yes
```

**Local key** — one-time fetch from the Tuya IoT Platform:

1. Create a **Cloud Project**. Its data center must match your app account's region — check *Smart Life → Me → Settings → Account and Security → Region*.
2. Enable **IoT Core** and **Authorization Token Management** for the project.
3. **Link the app account**: *Devices → Link Tuya App Account → scan the QR code from the app*.
4. Open the device → **Local Key**.

> ⚠️ Do **not** use `python -m tinytuya wizard` in this project. It persists the API secret and device keys to `tinytuya.json` / `devices.json` on disk. The wizard here writes only what the server needs, into `.env`.

> The local key rotates when the bulb is re-paired or factory-reset — re-fetch it then.

---

## Hermes Agent integration

Add the server to `~/AppData/Local/hermes/config.yaml`:

```yaml
mcp_servers:
  tuya-bulb:
    command: C:/path/to/tuya-bulb-mcp/.venv/Scripts/python.exe
    args:
      - C:/path/to/tuya-bulb-mcp/tuya_bulb_mcp_server.py
    timeout: 120
```

Or use the CLI, which validates the connection and discovers the tools before saving:

```bash
hermes mcp add tuya-bulb \
  --command "C:/path/to/tuya-bulb-mcp/.venv/Scripts/python.exe" \
  --args "C:/path/to/tuya-bulb-mcp/tuya_bulb_mcp_server.py"
```

Verify:

```bash
hermes mcp test tuya-bulb
```

```
✓ Connected (1688ms)
✓ Tools discovered: 4
    get_status   turn_on   turn_off   set_state
```

Then load them into the running session:

```
/reload-mcp
```

Tools appear namespaced — `mcp__tuya_bulb__get_status`, `mcp__tuya_bulb__turn_on`, and so on — and the agent routes natural language to them:

> "is the bulb on?" → `get_status`
> "turn the light off" → `turn_off`
> "make it warm white, 40%" → `set_state(temperature=40, brightness=40)`
> "back to normal" → `set_state(preset="baseline")`

### Other MCP clients

Any stdio MCP client works. Claude Desktop (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "tuya-bulb": {
      "command": "C:/path/to/tuya-bulb-mcp/.venv/Scripts/python.exe",
      "args": ["C:/path/to/tuya-bulb-mcp/tuya_bulb_mcp_server.py"]
    }
  }
}
```

---

## Tools

### `get_status`

Read-only. Returns power, mode, brightness, colour temperature, colour (raw + decoded HSV) and all raw datapoints.

```json
{
  "success": true,
  "power": "on",
  "mode": "colour",
  "brightness": 500,
  "color_temperature": 475,
  "color": { "raw": "000003e803e8", "decoded": { "hue": 0, "saturation": 1000, "value": 1000 } },
  "raw_dps": { "20": true, "21": "colour", "22": 500, "23": 475, "24": "000003e803e8" }
}
```

### `turn_on` / `turn_off`

Write DP20 (`true` / `false`) and verify with a read-back. No retries, no recovery writes — a failure is reported as a failure.

```json
{ "success": true, "action": "turn_off", "write": { "dp": 20, "value": false }, "verified": true, "power": "off" }
```

### `set_state`

Idempotent state change.

| Parameter | Type | Description |
|---|---|---|
| `mode` | `"white"` \| `"colour"` | Work mode |
| `color` | string | `red`, `orange`, `yellow`, `green`, `cyan`, `blue`, `purple`, `pink`, `white` |
| `hue` | 0–360 | Precise colour; alternative to `color` |
| `saturation` | 0–100 % | Colour saturation |
| `value` | 0–100 % | HSV value (colour brightness channel) |
| `brightness` | 1–100 % | White brightness |
| `temperature` | 0–100 % | Colour temperature (0 warm → 100 cool) |
| `preset` | `"baseline"` | Return to the captured known-good state |

Already in the requested state:

```json
{ "success": true, "changed": false, "reason": "already_set", "preset": "baseline" }
```

A real change:

```json
{
  "success": true, "changed": true, "verified": true,
  "verification": "read_back",
  "dps_written": { "22": 300, "23": 700, "21": "colour" },
  "state": { "brightness_pct": 30, "temperature_pct": 70 }
}
```

Result fields: `success`, `changed`, `verified`, `reason`, `verification` (`write_ack` | `read_back`), `dps_written`, `state`, `error`.

---

## How it stays safe

- **One device.** The target comes from `.env`. No tool accepts a device ID; there is no generic `set_datapoint`.
- **Bounded datapoints.** Only DP20–24 are writable: `20` power, `21` work_mode, `22` bright_value, `23` temp_value, `24` colour_data. DP25/26/34 (scene, countdown, unknown flag) are never touched.
- **No recovery guesses.** If a write fails, the server reports it and stops — it does not spray alternative commands at the device.
- **No secrets in output.** The local key and any `*key*` / `*secret*` / `*token*` fields are scrubbed from errors, logs and tool results.
- **Optional hard guard.** `TUYA_BULB_EXPECTED_DEVICE_ID` makes the server refuse to start against the wrong device.

### Baseline

`set_state(preset="baseline")` restores a **known-good pre-write snapshot** — the state captured before the first write, *not* a factory preset. See `baseline_state.example.json`. Capture your own with `get_status` first, keep it out of git, and update `BASELINE_DP` in the server if your bulb differs.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `Check device key or version` | Wrong local key or protocol version | Re-fetch the key; try `3.3` vs `3.4` |
| `Device Unreachable` / `Unable to Connect` | IP changed or bulb offline | Re-scan, set a DHCP reservation |
| `Timeout Waiting for Device` | Another client holds the connection, or weak Wi-Fi | Close the app's live view; retry |
| Scan finds nothing | AP/client isolation blocks local broadcast | Read IP from the router; device ID from the IoT console |
| Mode flips to `white` after brightness/temperature | Expected behaviour on this bulb family | Use `set_state(mode="colour", …)` or `preset="baseline"` |
| Partial multi-DP ACK | This family echoes only some datapoints | Normal — the server falls back to one read-back |
| `pip` TLS errors | Corporate proxy / TLS-inspecting antivirus | `pip install --trusted-host pypi.org --trusted-host files.pythonhosted.org -r requirements.txt` |

---

## Project layout

```
tuya_bulb_mcp_server.py       # the MCP server (stdio, 4 tools)
setup_wizard.py               # interactive .env setup + read-only verify
baseline_state.example.json   # template for the baseline snapshot
AGENTS.md / CLAUDE.md         # setup + safety instructions for AI coding agents
skills/tuya-bulb-mcp/SKILL.md # English agent skill (fast-path rules)
requirements.txt
.env.example
LICENSE
```

---

## Agent skill

`skills/tuya-bulb-mcp/SKILL.md` teaches an agent the fast path — call the MCP tool directly instead of taking terminal/script detours — plus the DP map and write rules.

```bash
# Hermes Agent
cp -r skills/tuya-bulb-mcp "$LOCALAPPDATA/hermes/skills/"     # Windows
cp -r skills/tuya-bulb-mcp ~/.hermes/skills/                  # Linux / macOS
```

---

## Development

Local-only helper scripts (status dump, single-DP write tests, MCP regression harness) are **gitignored** — they are tuned to one specific bulb and are not part of this repository. The shipped server is self-contained.

A safe smoke test after any change: `set_state(preset="baseline")` must return `already_set` without writing anything.

---

## Credits

- [TinyTuya](https://github.com/jasonacox/tinytuya) — local Tuya protocol implementation
- [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk) — server framework
- DP mapping verified against a `light_ty` family bulb (protocol 3.3)

## License

[MIT](LICENSE) © 2026 Can Yurtaçan

Use it, fork it, ship it. Attribution appreciated, not required.
