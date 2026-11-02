#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tuya bulb — minimal local MCP server (stdio)

Local control for ONE Tuya / Smart Life Wi-Fi bulb over the LAN (TinyTuya).
Four tools (namespace 'tuya-bulb' -> mcp__tuya_bulb__<tool>):
  - get_status   (read-only state summary)
  - turn_on      (writes DP20=true only + verifies)
  - turn_off     (writes DP20=false only + verifies)
  - set_state    (mode/colour/brightness/temperature/baseline; DP20-24; up to 2 ordered writes)

Rules (by design, do not change):
  - No other device; no tool accepts a device_id parameter, no generic tool.
    The server controls ONLY the device in TUYA_BULB_DEVICE_ID from .env;
    optional hard guard: refuse to start unless it matches TUYA_BULB_EXPECTED_DEVICE_ID.
  - Writable datapoints: DP20 (power) and via set_state DP21/22/23/24.
    DP25/26/34 are NEVER written.
  - No generic datapoint write tool (no set_datapoint etc. by design).
  - The local key is read from .env only; it never appears in logs,
    tool results or exceptions (scrub layer active). No hardcoded secrets.
  - Transport: stdio. No HTTP/ports are opened.

Run (spawned automatically once registered in the MCP client):
  .venv\\Scripts\\python.exe tuya_bulb_mcp_server.py
"""

import json
import os
import time
from typing import Annotated, Optional

import tinytuya
from mcp.server.fastmcp import FastMCP
from pydantic import Field

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(PROJECT_DIR, ".env")
BASELINE_PATH = os.path.join(PROJECT_DIR, "baseline_state.json")

WRITE_DP = 20  # power datapoint (turn_on/off)

mcp = FastMCP("tuya-bulb", log_level="WARNING")


# ------------------------------------------------------------------ config
def _load_env(path):
    cfg = {}
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            cfg[k.strip().removeprefix("export ")] = v.strip()
    return cfg


def _load_config():
    needed_new = (
        "TUYA_BULB_DEVICE_ID",
        "TUYA_BULB_IP",
        "TUYA_BULB_VERSION",
        "TUYA_BULB_LOCAL_KEY",
    )
    if not os.path.exists(ENV_PATH):
        raise SystemExit("tuya-bulb MCP: .env not found: %s" % ENV_PATH)
    cfg = _load_env(ENV_PATH)
    dev_id = cfg.get("TUYA_BULB_DEVICE_ID", "")
    ip = cfg.get("TUYA_BULB_IP", "")
    ver = cfg.get("TUYA_BULB_VERSION", "")
    key = cfg.get("TUYA_BULB_LOCAL_KEY", "")
    missing = [k for k, v in zip(needed_new, (dev_id, ip, ver, key)) if not v]
    if missing:
        raise SystemExit("tuya-bulb MCP: missing .env field(s): %s" % ", ".join(missing))
    expected_id = (os.environ.get("TUYA_BULB_EXPECTED_DEVICE_ID") or
                   cfg.get("TUYA_BULB_EXPECTED_DEVICE_ID", "")).strip()
    if expected_id and dev_id != expected_id:
        raise SystemExit(
            "tuya-bulb MCP: TUYA_BULB_DEVICE_ID does not match "
            "TUYA_BULB_EXPECTED_DEVICE_ID; refusing to start."
        )
    if ver not in ("3.3", "3.4"):
        raise SystemExit("tuya-bulb MCP: unsupported protocol version (use 3.3 or 3.4).")
    return {"id": dev_id, "ip": ip, "ver": float(ver), "key": key}


CFG = _load_config()


# ------------------------------------------------------------------ safety
def _scrub(text):
    s = str(text)
    key = CFG.get("key")
    if key and key in s:
        s = s.replace(key, "[REDACTED]")
    return s


def _sanitize(obj):
    """Mask field names containing key/secret/token/sign and scrub secret values."""
    def walk(o):
        if isinstance(o, dict):
            out = {}
            for k, v in o.items():
                kl = str(k).lower()
                if any(t in kl for t in ("key", "secret", "token", "sign")):
                    out[k] = "[REDACTED]"
                else:
                    out[k] = walk(v)
            return out
        if isinstance(o, list):
            return [walk(x) for x in o]
        if isinstance(o, str):
            return _scrub(o)
        return o
    return walk(obj)


# ------------------------------------------------------------------ device
def _device():
    d = tinytuya.BulbDevice(
        CFG["id"], CFG["ip"], CFG["key"],
        dev_type="default", version=CFG["ver"],
        connection_timeout=6, connection_retry_limit=2, connection_retry_delay=1,
    )
    d.set_version(CFG["ver"])
    d.set_socketTimeout(8)
    return d


def _read_dps(d, attempts=2):
    """Read-only status. Returns (dps dict or None, error string or None)."""
    last_err = None
    for attempt in range(max(1, attempts)):
        try:
            data = d.status()
        except Exception as exc:
            data = None
            last_err = "%s: %s" % (type(exc).__name__, _scrub(exc))
        if isinstance(data, dict) and isinstance(data.get("dps"), dict):
            dps = data["dps"]
            if isinstance(dps.get("20"), bool):
                return _sanitize(dps), None
            last_err = "unsupported device status: expected boolean power DP20"
        elif data is not None:
            if isinstance(data, dict):
                last_err = "status error: Err=%s Error=%s" % (
                    _scrub(data.get("Err")), _scrub(data.get("Error")))
            else:
                last_err = "unexpected status response type"
        if attempt == 0:
            time.sleep(1.5)
    return None, last_err or "no status response"


def _power_str(dps):
    v = dps.get("20")
    if v is True:
        return "on"
    if v is False:
        return "off"
    return None


def _decode_colour(raw):
    if isinstance(raw, str) and len(raw) == 12:
        try:
            return {
                "format": "HHHHSSSSVVVV (12-hex HSV)",
                "hue": int(raw[0:4], 16),
                "saturation": int(raw[4:8], 16),
                "value": int(raw[8:12], 16),
            }
        except ValueError:
            return None
    return None


# ------------------------------------------------------------------ tools
@mcp.tool(
    name="get_status",
    description=(
        "Read the Tuya bulb state — read-only status query, never writes. "
        "Examples: \"is the light on?\", \"what is the bulb state?\" -> this tool. "
        "Returns: power (on/off), mode, brightness, color temperature, color."
    ),
)
def tuya_bulb_get_status() -> dict:
    """Tuya bulb state summary (read-only)."""
    try:
        d = _device()
    except Exception as exc:
        return {"success": False, "device": "Tuya bulb",
                "error": _scrub("%s: %s" % (type(exc).__name__, exc))}
    dps, err = _read_dps(d)
    if dps is None:
        return {"success": False, "device": "Tuya bulb", "error": err}
    return {
        "success": True,
        "device": "Tuya bulb",
        "read_only": True,
        "power": _power_str(dps),
        "mode": dps.get("21"),
        "brightness": dps.get("22"),
        "color_temperature": dps.get("23"),
        "color": {"raw": dps.get("24"), "decoded": _decode_colour(dps.get("24"))},
        "raw_dps": dps,
    }


def _power_action(want_on):
    """Single write: set_value(20, want_on) + status verification. No recovery writes."""
    wanted = bool(want_on)
    action = "turn_on" if wanted else "turn_off"
    result = {
        "success": False,
        "device": "Tuya bulb",
        "action": action,
        "write": {"dp": WRITE_DP, "value": wanted},
    }
    try:
        d = _device()
    except Exception as exc:
        result["error"] = _scrub("%s: %s" % (type(exc).__name__, exc))
        result["note"] = "device handle could not be created; NO write was sent"
        return result

    # Check current power first: repeat requests should not send redundant writes.
    pre, read_error = _read_dps(d)
    if pre is None:
        # A transient read failure should not permanently block a power command.
        # Unsupported datapoints or unexpected status responses must still fail closed.
        detail = (read_error or "").lower()
        transient = any(term in detail for term in (
            "timeout", "timed out", "connection", "unreachable", "no status response",
        ))
        if not transient:
            result["error"] = read_error or "current state could not be read"
            result["note"] = "NO write was sent"
            return result
        result["precheck_unavailable"] = True
    if pre is not None and pre.get("20") == wanted:
        result.update({"success": True, "changed": False, "reason": "already_set",
                       "verified": True, "power": "on" if wanted else "off"})
        result.pop("write")
        return result

    # Single write: DP20 only
    try:
        ack = d.set_value(WRITE_DP, wanted)
    except Exception as exc:
        result["error"] = _scrub("%s: %s" % (type(exc).__name__, exc))
        result["note"] = "write failed; NO further write attempted (no recovery)"
        dps, _ = _read_dps(d)
        if dps is not None:
            result["power"] = _power_str(dps)
        return result

    result["write"]["ack"] = _sanitize(ack if ack is not None else {})

    # Verification: independent status read (no write retries)
    dps, err = _read_dps(d)
    result["verified"] = bool(dps is not None and dps.get("20") == wanted)
    if dps is not None:
        result["power"] = _power_str(dps)

    if result["verified"]:
        result["success"] = True
        result["changed"] = True
        result["note"] = ("only DP20 was written; verified with an independent "
                          "status() call; DP21-34 untouched")
    else:
        result["error"] = err or "write could not be verified with status"
        result["note"] = "NO recovery write was sent (by design)"
    return result


@mcp.tool(
    name="turn_on",
    description=(
        "Turn the Tuya bulb ON — writes only power datapoint DP20=true, "
        "then verifies with status. Examples: \"turn the light on\", "
        "\"turn on the bulb\" -> this tool. No further writes on failure."
    ),
)
def tuya_bulb_turn_on() -> dict:
    """Turn the Tuya bulb on (DP20=true only)."""
    return _power_action(True)


@mcp.tool(
    name="turn_off",
    description=(
        "Turn the Tuya bulb OFF — writes only power datapoint DP20=false, "
        "then verifies with status. Examples: \"turn the light off\", "
        "\"turn off the bulb\" -> this tool. No further writes on failure."
    ),
)
def tuya_bulb_turn_off() -> dict:
    """Turn the Tuya bulb off (DP20=false only)."""
    return _power_action(False)


# ------------------------------------------------------------------ set_state
# A local baseline is captured by setup_wizard.py during read-only setup.
# Never fall back to example values: incorrect fallback would write an
# unrelated state to the bulb. The file is deliberately gitignored.
def _load_baseline():
    try:
        with open(BASELINE_PATH, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as exc:
        raise ValueError(
            "Baseline is unavailable; run setup_wizard.py to capture it."
        ) from exc
    if not isinstance(data, dict) or data.get("device_id") != CFG["id"]:
        raise ValueError("Baseline device identity is missing or does not match; refusing to restore.")
    dps = data.get("baseline_dps")
    keys = ("20", "21", "22", "23", "24")
    if not isinstance(dps, dict) or not all(key in dps for key in keys):
        raise ValueError("Invalid baseline: expected DP20–24.")
    colour = _decode_colour(dps["24"])
    if (not isinstance(dps["20"], bool)
            or dps["21"] not in ("white", "colour")
            or any(type(dps[key]) is not int or not 0 <= dps[key] <= 1000 for key in ("22", "23"))
            or colour is None
            or not 0 <= colour["hue"] <= 360
            or not 0 <= colour["saturation"] <= 1000
            or not 0 <= colour["value"] <= 1000):
        raise ValueError("Invalid baseline: unsupported datapoint types or ranges.")
    return {key: dps[key] for key in keys}

# Named colours -> (hue 0-360, saturation 0-1000). English names only.
_NAMED_COLOURS = {
    "red": (0, 1000),
    "orange": (30, 1000),
    "yellow": (60, 1000),
    "green": (120, 1000),
    "cyan": (180, 1000),
    "blue": (240, 1000),
    "purple": (270, 1000),
    "pink": (330, 600),
}
_WHITE_WORDS = ("white",)


def _norm_key(s):
    return str(s).strip().lower()


def _clamp_pct(v):
    return max(0, min(100, int(round(float(v)))))


def _scale10(pct):
    """Percent -> Tuya 0-1000 scale (pct x 10)."""
    return _clamp_pct(pct) * 10


def _hex4(n):
    return "%04x" % max(0, min(65535, int(n)))


def _encode_colour(hue_deg, sat_1000, val_1000):
    """Tuya 12-hex HSV: HHHH(0-360) SSSS(0-1000) VVVV(0-1000)."""
    return _hex4(hue_deg) + _hex4(sat_1000) + _hex4(val_1000)


def _current_colour_hsv(dps):
    dec = _decode_colour(dps.get("24"))
    if dec:
        return dec["hue"], dec["saturation"], dec["value"]
    return 0, 1000, 1000


@mcp.tool(
    name="set_state",
    description=(
        "Set the Tuya bulb state: white/colour mode, colour (name or "
        "hue/saturation/value), brightness (%), colour temperature (%) and "
        "return to the captured baseline. Examples: \"make it white\" -> "
        "mode=\"white\"; \"make it red\" -> color=\"red\"; \"set brightness to "
        "50%\" -> brightness=50; \"warmer/cooler\" -> temperature; \"back to "
        "baseline\" -> preset=\"baseline\". Idempotent: writes nothing when "
        "already set (already_set). On brightness/temperature writes the device "
        "switches work_mode to 'white', so ordering is handled internally. "
        "Only DP20-24 are used; DP25/26/34 are never touched."
    ),
)
def tuya_bulb_set_state(
    mode: Annotated[Optional[str], Field(description="'white' or 'colour' (e.g. \"make it white\").")] = None,
    color: Annotated[Optional[str], Field(description="Colour name: red, green, blue, yellow, orange, purple, pink, cyan, white.")] = None,
    hue: Annotated[Optional[int], Field(description="Hue 0-360 (0=red). Fine-grained alternative to color.")] = None,
    saturation: Annotated[Optional[int], Field(description="Saturation percent 0-100.")] = None,
    value: Annotated[Optional[int], Field(description="Colour brightness channel percent 0-100 (HSV value).")] = None,
    brightness: Annotated[Optional[int], Field(description="Brightness percent 1-100 (e.g. \"50%\" -> 50).")] = None,
    temperature: Annotated[Optional[int], Field(description="Colour temperature percent 0-100 (DP23 = pct x 10).")] = None,
    preset: Annotated[Optional[str], Field(description="Only 'baseline': return to the captured normal state.")] = None,
) -> dict:
    """Short state change: idempotent, minimal writes + at most 1 read-back."""
    preset_n = _norm_key(preset) if preset is not None else None
    if preset is not None and preset_n != "baseline":
        return {"success": False, "error": _scrub("Invalid preset: %r (supported: 'baseline')" % preset)}

    mode_n = _norm_key(mode) if mode is not None else None
    if mode is not None and mode_n not in ("white", "colour", "color"):
        return {"success": False, "error": _scrub("Invalid mode: %r (supported: 'white', 'colour')" % mode)}

    if all(v is None for v in (mode, color, hue, saturation, value, brightness, temperature, preset)):
        return {"success": False,
                "error": "At least one parameter is required (mode/color/hue/saturation/value/brightness/temperature/preset)."}

    try:
        d = _device()
    except Exception as exc:
        return {"success": False, "error": _scrub("%s: %s" % (type(exc).__name__, exc)),
                "note": "device handle could not be created; NO write was sent"}

    pre, perr = _read_dps(d)  # single pre-read for idempotency + colour composition
    if pre is None:
        return {"success": False, "error": "Current state could not be read (%s)" % perr,
                "note": "NO write was sent"}
    if not all(key in pre for key in ("20", "21", "22", "23", "24")):
        return {"success": False, "error": "Unsupported device DP scheme (requires DP20–24).",
                "note": "NO write was sent"}
    if pre["21"] not in ("white", "colour"):
        return {"success": False,
                "error": "Device is not in white/colour mode; switch mode in the app first.",
                "note": "NO write was sent"}

    used_baseline = False
    desired = {}
    labels = {}

    if preset_n == "baseline":
        try:
            desired.update(_load_baseline())
        except ValueError as exc:
            return {"success": False, "error": str(exc), "note": "NO write was sent"}
        used_baseline = True
        labels["preset"] = "baseline"

    if mode_n is not None:
        desired["21"] = "white" if mode_n == "white" else "colour"
        labels["mode"] = desired["21"]

    colour_req = None
    if color is not None:
        cn = _norm_key(color)
        if cn in _WHITE_WORDS:
            desired["21"] = "white"
            labels["color"] = "white"
            labels["mode"] = "white"
        else:
            entry = _NAMED_COLOURS.get(cn)
            if entry is None:
                return {"success": False,
                        "error": _scrub("Unknown colour: %r (supported: %s)"
                                        % (color, ", ".join(sorted(set(_NAMED_COLOURS)))))}
            h, s = entry
            if hue is not None:
                h = int(hue)
            if saturation is not None:
                s = _scale10(saturation)
            colour_req = (h, s, _scale10(value) if value is not None else None)
            labels["color"] = cn
    elif hue is not None or saturation is not None or value is not None:
        ch, cs, cv = _current_colour_hsv(pre)
        colour_req = (
            int(hue) if hue is not None else ch,
            _scale10(saturation) if saturation is not None else cs,
            _scale10(value) if value is not None else cv,
        )

    if colour_req is not None:
        h, s, v = colour_req
        if v is None:
            v = _current_colour_hsv(pre)[2]
        h = max(0, min(360, int(h)))
        desired["24"] = _encode_colour(h, s, v)
        desired["21"] = "colour"
        labels.update({"mode": "colour", "colour_data": desired["24"],
                       "hue": h, "saturation": s, "value": v})

    if brightness is not None:
        bp = max(1, _clamp_pct(brightness))
        desired["22"] = bp * 10
        labels["brightness_pct"] = bp
        labels["brightness"] = desired["22"]

    if temperature is not None:
        tp = _clamp_pct(temperature)
        desired["23"] = tp * 10
        labels["temperature_pct"] = tp
        labels["temperature"] = desired["23"]

    # ---- idempotency: only write changed DPs
    writes = {dp: val for dp, val in desired.items() if pre.get(dp) != val}

    refs = {}
    if used_baseline:
        refs["preset"] = "baseline"

    if not writes:
        result = {"success": True, "changed": False, "reason": "already_set"}
        result.update(refs)
        result["state"] = labels
        return result

    # ---- write order (verified device behaviour):
    #  Writing DP22/DP23 flips work_mode to 'white'; in a mixed single packet
    #  'white' wins. So white-ops (22/23) go FIRST, colour-ops (21/24, with a
    #  21='colour' re-assert when needed) LAST, power (20) last.
    white_ops = {dp: writes[dp] for dp in ("22", "23") if dp in writes}
    colour_ops = {dp: writes[dp] for dp in ("21", "24") if dp in writes}
    power_ops = {dp: writes[dp] for dp in ("20",) if dp in writes}
    intended_mode = desired.get("21")
    if white_ops and intended_mode == "colour":
        colour_ops.setdefault("21", "colour")  # undo the white flip
    if power_ops:
        if colour_ops:
            colour_ops.update(power_ops)
        elif white_ops:
            white_ops.update(power_ops)

    commands = [c for c in (white_ops, colour_ops) if c]
    if not commands:
        commands = [dict(writes)]
    all_written = {}
    for cmd in commands:
        all_written.update(cmd)

    # ---- write commands (at most 2: white-ops first, then colour-ops)
    last_ack = None
    completed = {}
    attempted = {}
    try:
        for index, cmd in enumerate(commands):
            attempted.update(cmd)
            last_ack = d.set_multiple_values(cmd)
            completed.update(cmd)
            if index < len(commands) - 1:
                time.sleep(0.2)
    except Exception as exc:
        return {"success": False,
                "error": _scrub("%s: %s" % (type(exc).__name__, exc)),
                "note": "write failed; NO further write attempted (no recovery)",
                "dps_attempted": attempted, "dps_completed": completed}

    # ---- verification: single-command write-ack first, else at most 1 read-back
    verified = False
    method = None
    if len(commands) == 1:
        ack_dps = (last_ack.get("dps")
                   if isinstance(last_ack, dict) and isinstance(last_ack.get("dps"), dict) else None)
        if ack_dps is not None and all(
            ack_dps.get(dp, ack_dps.get(str(dp))) == val for dp, val in all_written.items()
        ):
            verified = True
            method = "write_ack"
    if not verified:
        time.sleep(0.5)  # short settle for state reflection
        post, _perr = _read_dps(d, attempts=2)
        if post is not None and all(post.get(dp) == val for dp, val in all_written.items()):
            verified = True
            method = "read_back"

    result = {"success": bool(verified), "changed": True, "verified": bool(verified)}
    result.update(refs)
    if method:
        result["verification"] = method
    result["dps_written"] = all_written
    if len(commands) > 1:
        result["write_commands"] = len(commands)
    result["state"] = labels
    if not verified:
        result["error"] = "write could not be verified (ack/read-back mismatch)"
        result["note"] = "NO recovery write was sent"
        result["ack"] = _sanitize(last_ack if last_ack is not None else {})
    return result


# ------------------------------------------------------------------ main
if __name__ == "__main__":
    # stdio transport (default) — no HTTP/ports
    mcp.run()
