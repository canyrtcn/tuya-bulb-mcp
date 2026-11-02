# AGENTS.md — instructions for AI coding agents

You are helping a user set up **tuya-bulb-mcp**: a minimal local MCP server (stdio, TinyTuya) that controls exactly ONE Tuya / Smart Life Wi-Fi bulb over the LAN. No cloud at runtime.

Read this file fully before doing anything. Follow the rules; do not improvise around them.

## Non-negotiable rules

1. **Secrets:** the device local key lives ONLY in `.env` (gitignored). Never echo, print, log, or commit it. Never create `tinytuya.json` / `devices.json` / `tuya-raw.json` (they persist secrets). If the key is needed, have the user paste it into `.env` directly — never through chat.
2. **One device only:** the server controls exactly the device configured in `TUYA_BULB_DEVICE_ID`. Do NOT add device-selection parameters and do NOT add any generic "datapoint write" / "any device" tool.
3. **Writes are limited to DP20–24:** `20` power (bool), `21` work_mode, `22` bright_value, `23` temp_value, `24` colour_data. **DP25 / DP26 / DP34 must never be written.**
4. **Do not guess DP numbers or value formats.** Run `get_status` first. If the bulb uses a different scheme (e.g. the common 1–5 mapping), adjust the DP map deliberately inside `tuya_bulb_mcp_server.py` and re-verify **read-only** before any write.
5. **Verify every write with a status read-back.** The tools already do this; report failures honestly and do not retry blindly.
6. **Do not use `python -m tinytuya wizard` in this project's flow** — it persists credentials to disk. The local key is a one-time fetch from the user's Tuya IoT Cloud project (Cloud → link Smart Life app account → device local key).

## Setup (repeatable, ~5 minutes)

### Windows (PowerShell)

```powershell
git clone <repo-url> tuya-bulb-mcp
cd tuya-bulb-mcp
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -m tinytuya scan 25 -nocolor -yes   # device id / IP / version (or use setup_wizard.py --scan)
# user fills .env (device id, IP, version, local key; optional TUYA_BULB_EXPECTED_DEVICE_ID hard guard), then:
.\.venv\Scripts\python.exe setup_wizard.py                 # read-only check
```

### Linux

```bash
git clone <repo-url> tuya-bulb-mcp
cd tuya-bulb-mcp
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python setup_wizard.py   # fill .env + read-only check (use --scan first if needed)
```

### macOS

```bash
git clone <repo-url> tuya-bulb-mcp
cd tuya-bulb-mcp
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python setup_wizard.py
```

> **Guided alternative:** `python setup_wizard.py` (Windows: `.\.venv\Scripts\python.exe setup_wizard.py`) — prompts for device id / IP / version and the local key (hidden input), writes `.env`, and finishes with one read-only `status()` check. Add `--scan` to run a LAN scan first.

> If `pip` fails with TLS/certificate errors (corporate proxy or TLS-inspecting antivirus), retry with:
> `--trusted-host pypi.org --trusted-host files.pythonhosted.org`

## Verify before trusting

1. `.env` is filled (device id / IP / version / local key).
2. Read-only check passes: `setup_wizard.py` prints `[OK] Device responded` (one `status()` call, no writes) — note the values of DPs `20/21/22/23/24`.
3. Only then wire the MCP server into the client.

## Agent skill

`skills/tuya-bulb-mcp/SKILL.md` contains the English fast-path skill for AI agents (direct tool calls, no terminal detours). Load it into your agent's skill system if it supports skills.

## Wire into an MCP client

The server is **stdio only** — the client spawns the venv python with the server script as an argument. Example (Hermes Agent):

```yaml
mcp_servers:
  tuya-bulb:
    command: C:/path/to/tuya-bulb-mcp/.venv/Scripts/python.exe
    args:
      - C:/path/to/tuya-bulb-mcp/tuya_bulb_mcp_server.py
    timeout: 120
```

After registering, reload/restart the client and confirm discovery shows **exactly four** tools: `get_status`, `turn_on`, `turn_off`, `set_state` (in Hermes they render as `mcp__tuya_bulb__*`).

## Tool contract (keep stable)

| Tool | Behaviour |
|---|---|
| `get_status()` | Read-only summary: `power`, `mode`, `brightness` (DP22), `color_temperature` (DP23), `color` (`raw` + decoded HSV), `raw_dps`. |
| `turn_on()` / `turn_off()` | Single DP20 write + read-back verification. |
| `set_state(mode?, color?, hue?, saturation?, value?, brightness?, temperature?, preset?)` | Idempotent: returns `already_set` with no write when nothing changes. Ordered writes: white-ops (22/23) first, colour-ops (21/24) last, because this bulb family auto-switches to `white` mode on bright/temp writes; multi-DP ACKs are partial. Verification = write-ack, else at most one read-back. `preset="baseline"` restores the captured baseline. |

Result shape: `{success, changed, verified?, reason?, verification?, dps_written?, state?}`.

## Safe write test (user's bulb only)

- `set_state(preset="baseline")` on a bulb already at baseline must return `{"success": true, "changed": false, "reason": "already_set"}` — proves connectivity without moving the device.
- Power cycle: `turn_off` → verify `power` flips to `off` → `turn_on` → verify `on`. Leave the bulb as you found it.

## Troubleshooting

- **`DEVICE KEY required` in scan** → local key missing/wrong; re-fetch from the cloud (re-pairing or factory reset rotates the key).
- **Connects but status times out** → wrong IP (DHCP change) or another client holding the connection; re-scan and set a DHCP reservation.
- **`Check device key or version`** → wrong key or protocol version; confirm `3.3`/`3.4` from the scan output.
- **Partial multi-DP ACKs** → normal on these bulbs (often only the first dp is echoed). The server falls back to one read-back; never treat a partial ACK alone as failure.
- **Mode flips to `white` after brightness/temperature writes** → expected device behaviour; use `set_state(mode="colour", ...)` or `preset="baseline"` to return.

## Adapting to a different bulb

DP numbers and value scales vary between Tuya firmwares. The constants live in `tuya_bulb_mcp_server.py`:

- `EXPECTED_DEVICE_ID` — optional hard guard (must match `.env`)
- `WRITE_DP` — power datapoint (20 here)
- `BASELINE_DP` — captured pre-write baseline (replace with your own capture)
- `_NAMED_COLOURS`, `_scale10` — colour hue table and percentage → 0–1000 scaling

Change them deliberately, verify read-only first, and only then allow writes.
