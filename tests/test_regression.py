"""Offline regression checks; never connect to a real bulb."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
KEY = "abcdefghijklmnop"
DPS = {"20": True, "21": "colour", "22": 500, "23": 475, "24": "000003e803e8"}


def load_wizard():
    spec = importlib.util.spec_from_file_location("setup_wizard", ROOT / "setup_wizard.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeBulb:
    def __init__(self, status=None, exception=None):
        self.dps = dict(status or DPS)
        self.exception = exception
        self.writes = []

    def set_version(self, _version):
        pass

    def set_socketTimeout(self, _seconds):
        pass

    def status(self):
        if self.exception:
            raise self.exception
        return {"dps": dict(self.dps)}

    def set_value(self, dp, value):
        self.writes.append({str(dp): value})
        self.dps[str(dp)] = value
        return {"dps": {str(dp): value}}

    def set_multiple_values(self, values):
        self.writes.append(dict(values))
        self.dps.update(values)
        return {"dps": dict(values)}


def tinytuya_module(bulb):
    module = types.ModuleType("tinytuya")
    module.BulbDevice = lambda *args, **kwargs: bulb
    return module


class DummyMCP:
    def __init__(self, *args, **kwargs):
        pass

    def tool(self, **kwargs):
        return lambda function: function

    def run(self):
        pass


def load_server(directory, bulb, guard="", environment_guard=""):
    env = Path(directory) / ".env"
    env.write_text(
        "TUYA_BULB_DEVICE_ID=example123\n"
        "TUYA_BULB_IP=192.0.2.10\n"
        "TUYA_BULB_VERSION=3.3\n"
        "TUYA_BULB_LOCAL_KEY=" + KEY + "\n"
        "TUYA_BULB_EXPECTED_DEVICE_ID=" + guard + "\n",
        encoding="utf-8",
    )
    fastmcp = types.ModuleType("mcp.server.fastmcp")
    fastmcp.FastMCP = DummyMCP
    modules = {
        "tinytuya": tinytuya_module(bulb),
        "mcp": types.ModuleType("mcp"),
        "mcp.server": types.ModuleType("mcp.server"),
        "mcp.server.fastmcp": fastmcp,
    }
    source = (ROOT / "tuya_bulb_mcp_server.py").read_text(encoding="utf-8")
    namespace = {"__file__": str(Path(directory) / "tuya_bulb_mcp_server.py"),
                 "__name__": "_test_mcp_server"}
    with mock.patch.dict(sys.modules, modules), mock.patch.dict(
        os.environ, {"TUYA_BULB_EXPECTED_DEVICE_ID": environment_guard}, clear=False
    ):
        exec(compile(source, namespace["__file__"], "exec"), namespace)
    return namespace


class WizardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.wizard = load_wizard()
        self.env = Path(self.temp.name) / ".env"
        self.baseline = Path(self.temp.name) / "baseline_state.json"

    def test_replace_guard_and_preserve_other_keys(self):
        self.env.write_text("CUSTOM=keep\nTUYA_BULB_EXPECTED_DEVICE_ID=stale\n",
                            encoding="utf-8")
        values = {
            "TUYA_BULB_DEVICE_ID": "example123",
            "TUYA_BULB_IP": "192.0.2.10",
            "TUYA_BULB_VERSION": "3.3",
            "TUYA_BULB_LOCAL_KEY": KEY,
            "TUYA_BULB_EXPECTED_DEVICE_ID": "",
        }
        self.wizard.upsert_env(str(self.env), values)
        content = self.env.read_text(encoding="utf-8")
        self.assertIn("CUSTOM=keep", content)
        self.assertEqual(content.count("TUYA_BULB_EXPECTED_DEVICE_ID="), 1)
        self.assertNotIn("stale", content)
        if os.name == "posix":
            self.assertEqual(self.env.stat().st_mode & 0o777, 0o600)

    def test_device_compatibility(self):
        self.assertTrue(self.wizard.valid_dps({"dps": DPS}))
        self.assertFalse(self.wizard.valid_dps({"dps": {}}))
        self.assertFalse(self.wizard.valid_dps({"dps": {"1": True}}))
        self.assertFalse(self.wizard.valid_dps({"dps": {**DPS, "20": "yes"}}))

    def test_reject_bad_ip_version_and_key(self):
        for ip, version, key in [
            ("no host", "3.3", KEY),
            ("192.0.2.10", "bad", KEY),
            ("192.0.2.10", "3.3", "short"),
        ]:
            with self.assertRaises(ValueError):
                self.wizard.validate_values("example123", ip, version, key)

    def test_read_only_setup_captures_once(self):
        bulb = FakeBulb()
        values = {
            "TUYA_BULB_DEVICE_ID": "example123",
            "TUYA_BULB_IP": "192.0.2.10",
            "TUYA_BULB_VERSION": "3.3",
            "TUYA_BULB_LOCAL_KEY": KEY,
        }
        with mock.patch.object(self.wizard, "BASELINE_PATH", str(self.baseline)), \
             mock.patch.dict(sys.modules, {"tinytuya": tinytuya_module(bulb)}), \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertTrue(self.wizard.verify(values))
            self.assertEqual(json.loads(self.baseline.read_text())["baseline_dps"], DPS)
            self.assertEqual(json.loads(self.baseline.read_text())["device_id"], "example123")
            self.assertEqual(bulb.writes, [])
            bulb.dps["22"] = 700
            self.assertTrue(self.wizard.verify(values))
        self.assertEqual(json.loads(self.baseline.read_text())["baseline_dps"], DPS)

    def test_verification_masks_error_secret(self):
        bulb = FakeBulb(exception=RuntimeError("unexpected " + KEY))
        values = {
            "TUYA_BULB_DEVICE_ID": "example123",
            "TUYA_BULB_IP": "192.0.2.10",
            "TUYA_BULB_VERSION": "3.3",
            "TUYA_BULB_LOCAL_KEY": KEY,
        }
        output = io.StringIO()
        with mock.patch.dict(sys.modules, {"tinytuya": tinytuya_module(bulb)}), \
             contextlib.redirect_stdout(output):
            self.assertFalse(self.wizard.verify(values))
        self.assertNotIn(KEY, output.getvalue())
        self.assertIn("[REDACTED]", output.getvalue())

    def test_eof_fails_without_writing(self):
        with mock.patch.object(self.wizard, "ENV_PATH", str(self.env)), \
             mock.patch("builtins.input", side_effect=EOFError), \
             mock.patch("sys.argv", ["setup_wizard.py"]), \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.wizard.main(), 1)
        self.assertFalse(self.env.exists())

    def test_scan_failure_is_reported(self):
        with mock.patch.object(self.wizard.subprocess, "run", side_effect=OSError), \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertFalse(self.wizard.run_scan())

    def test_mismatched_or_legacy_baseline_is_preserved(self):
        bulb = FakeBulb()
        values = {
            "TUYA_BULB_DEVICE_ID": "example123",
            "TUYA_BULB_IP": "192.0.2.10",
            "TUYA_BULB_VERSION": "3.3",
            "TUYA_BULB_LOCAL_KEY": KEY,
        }
        for prior in (
            {"device_id": "another-device", "baseline_dps": DPS},
            {"baseline_dps": DPS},
        ):
            original = json.dumps(prior)
            self.baseline.write_text(original, encoding="utf-8")
            with mock.patch.object(self.wizard, "BASELINE_PATH", str(self.baseline)), \
                 mock.patch.dict(sys.modules, {"tinytuya": tinytuya_module(bulb)}), \
                 contextlib.redirect_stdout(io.StringIO()):
                self.assertFalse(self.wizard.verify(values))
            self.assertEqual(self.baseline.read_text(encoding="utf-8"), original)

    def test_scene_mode_guides_user_without_changes(self):
        bulb = FakeBulb(status={**DPS, "21": "scene"})
        values = {
            "TUYA_BULB_DEVICE_ID": "example123",
            "TUYA_BULB_IP": "192.0.2.10",
            "TUYA_BULB_VERSION": "3.3",
            "TUYA_BULB_LOCAL_KEY": KEY,
        }
        captured = io.StringIO()
        with mock.patch.dict(sys.modules, {"tinytuya": tinytuya_module(bulb)}), \
             mock.patch.object(self.wizard, "BASELINE_PATH", str(self.baseline)), \
             contextlib.redirect_stdout(captured):
            self.assertFalse(self.wizard.verify(values))
        self.assertIn("Switch to white or colour", captured.getvalue())
        self.assertFalse(self.baseline.exists())
        self.assertFalse(bulb.writes)

    def test_failed_verification_does_not_replace_configuration(self):
        old_text = "CUSTOM=untouched\n"
        self.env.write_text(old_text, encoding="utf-8")
        inputs = iter(["example123", "192.0.2.10", "3.3", ""])
        with mock.patch.object(self.wizard, "ENV_PATH", str(self.env)), \
             mock.patch("builtins.input", side_effect=lambda *_: next(inputs)), \
             mock.patch.object(self.wizard, "read_secret", return_value=KEY), \
             mock.patch.object(self.wizard, "verify", return_value=False), \
             mock.patch("sys.argv", ["setup_wizard.py"]), \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.wizard.main(), 2)
        self.assertEqual(self.env.read_text(encoding="utf-8"), old_text)

    def test_load_env_export_and_remove_stale_comments(self):
        self.env.write_text(
            "export TUYA_BULB_DEVICE_ID=example123\n"
            "# TUYA_BULB_EXPECTED_DEVICE_ID=stale\n"
            "CUSTOM=keep\n", encoding="utf-8")
        self.assertEqual(self.wizard.load_env(str(self.env))["TUYA_BULB_DEVICE_ID"], "example123")
        values = {
            "TUYA_BULB_DEVICE_ID": "example123",
            "TUYA_BULB_IP": "192.0.2.10",
            "TUYA_BULB_VERSION": "3.3",
            "TUYA_BULB_LOCAL_KEY": KEY,
            "TUYA_BULB_EXPECTED_DEVICE_ID": "",
        }
        self.wizard.upsert_env(str(self.env), values)
        content = self.env.read_text(encoding="utf-8")
        self.assertNotIn("stale", content)
        self.assertNotIn("export TUYA_BULB_DEVICE_ID", content)
        self.assertIn("CUSTOM=keep", content)

    def test_invalid_color_range_and_version_are_rejected(self):
        self.assertFalse(self.wizard.valid_dps({"dps": {**DPS, "24": "ffff03e803e8"}}))
        self.assertFalse(self.wizard.valid_dps({"dps": {**DPS, "22": 9999}}))
        with self.assertRaises(ValueError):
            self.wizard.validate_values("example123", "192.0.2.10", "3.5", KEY)


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.bulb = FakeBulb()

    def server(self, guard="", environment_guard=""):
        return load_server(self.temp.name, self.bulb, guard, environment_guard)

    def test_configured_identity_guard(self):
        with self.assertRaises(SystemExit):
            self.server(guard="different-device")

    def test_no_baseline_never_writes(self):
        ns = self.server()
        result = ns["tuya_bulb_set_state"](preset="baseline")
        self.assertFalse(result["success"])
        self.assertEqual(self.bulb.writes, [])

    def test_baseline_restores_saved_values_not_examples(self):
        baseline = {**DPS, "22": 650}
        (Path(self.temp.name) / "baseline_state.json").write_text(
            json.dumps({"device_id": "example123", "baseline_dps": baseline}), encoding="utf-8")
        ns = self.server()
        result = ns["tuya_bulb_set_state"](preset="baseline")
        self.assertTrue(result["success"])
        self.assertEqual(self.bulb.dps["22"], 650)
        self.assertEqual(len(self.bulb.writes), 2)
        self.assertEqual(self.bulb.writes, [{"22": 650}, {"21": "colour"}])
        self.assertEqual(result["verification"], "read_back")
        self.assertFalse(any(key in cmd for cmd in self.bulb.writes for key in ("20", "23", "24")))

    def test_power_idempotency(self):
        ns = self.server()
        self.assertEqual(ns["tuya_bulb_turn_on"]()["reason"], "already_set")
        self.assertEqual(self.bulb.writes, [])
        result = ns["tuya_bulb_turn_off"]()
        self.assertTrue(result["success"])
        self.assertEqual(self.bulb.writes, [{"20": False}])

    def test_unsupported_dp_scheme_never_writes(self):
        self.bulb = FakeBulb(status={"1": True})
        ns = self.server()
        result = ns["tuya_bulb_turn_off"]()
        self.assertFalse(result["success"])
        self.assertEqual(self.bulb.writes, [])

    def test_non_dictionary_status_does_not_crash(self):
        ns = self.server()
        class Broken:
            def status(self):
                return "not a dictionary"
        data, error = ns["_read_dps"](Broken(), attempts=1)
        self.assertIsNone(data)
        self.assertIn("unexpected", error)

    def test_environment_guard(self):
        with self.assertRaises(SystemExit):
            self.server(environment_guard="wrong-device")

    def test_invalid_protocol_version_aborts_cleanly(self):
        ns = self.server()
        env = Path(self.temp.name) / ".env"
        env.write_text(env.read_text().replace("VERSION=3.3", "VERSION=invalid"))
        with self.assertRaisesRegex(SystemExit, "unsupported protocol version"):
            ns["_load_config"]()

    def test_wrong_device_and_legacy_baselines_never_write(self):
        ns = self.server()
        for data in (
            {"device_id": "different-device", "baseline_dps": DPS},
            {"baseline_dps": DPS},
            {"device_id": "example123", "baseline_dps": {**DPS, "22": 9000}},
            {"device_id": "example123", "baseline_dps": {**DPS, "24": "ffff03e803e8"}},
        ):
            (Path(self.temp.name) / "baseline_state.json").write_text(json.dumps(data))
            result = ns["tuya_bulb_set_state"](preset="baseline")
            self.assertFalse(result["success"])
            self.assertEqual(self.bulb.writes, [])

    def test_turn_on_writes_and_verifies(self):
        self.bulb.dps["20"] = False
        ns = self.server()
        result = ns["tuya_bulb_turn_on"]()
        self.assertTrue(result["verified"])
        self.assertEqual(self.bulb.writes, [{"20": True}])

    def test_power_transient_read_failure_tries_write(self):
        class FlakyBulb(FakeBulb):
            calls = 0
            def status(self):
                self.calls += 1
                if self.calls <= 2:
                    raise TimeoutError("temporary read timeout")
                return super().status()
        self.bulb = FlakyBulb()
        ns = self.server()
        with mock.patch("time.sleep"):
            result = ns["tuya_bulb_turn_off"]()
        self.assertTrue(result["success"])
        self.assertTrue(result["precheck_unavailable"])
        self.assertEqual(self.bulb.writes, [{"20": False}])

    def test_set_state_order_and_read_back(self):
        ns = self.server()
        with mock.patch("time.sleep"):
            result = ns["tuya_bulb_set_state"](brightness=65, mode="colour")
        self.assertEqual(self.bulb.writes, [{"22": 650}, {"21": "colour"}])
        self.assertEqual(result["verification"], "read_back")
        self.assertTrue(result["verified"])

    def test_partial_command_failure_reports_completed_vs_attempted(self):
        class PartialBulb(FakeBulb):
            def set_multiple_values(self, values):
                if len(self.writes) >= 1:
                    raise ConnectionError("second command failed")
                return super().set_multiple_values(values)
        self.bulb = PartialBulb()
        ns = self.server()
        with mock.patch("time.sleep"):
            result = ns["tuya_bulb_set_state"](brightness=65, mode="colour")
        self.assertFalse(result["success"])
        self.assertEqual(result["dps_completed"], {"22": 650})
        self.assertEqual(result["dps_attempted"], {"22": 650, "21": "colour"})
        self.assertEqual(self.bulb.writes, [{"22": 650}])

    def test_ack_mismatch_and_read_back_mismatch(self):
        class IgnoringBulb(FakeBulb):
            def set_multiple_values(self, values):
                self.writes.append(dict(values))
                return {"dps": {"99": True}}
        self.bulb = IgnoringBulb()
        ns = self.server()
        with mock.patch("time.sleep"):
            result = ns["tuya_bulb_set_state"](color="blue")
        self.assertFalse(result["success"])
        self.assertFalse(result["verified"])
        self.assertEqual(len(self.bulb.writes), 1)

    def test_set_state_rejects_scene_mode(self):
        self.bulb.dps["21"] = "scene"
        ns = self.server()
        result = ns["tuya_bulb_set_state"](brightness=50)
        self.assertFalse(result["success"])
        self.assertEqual(self.bulb.writes, [])

    def test_secret_redaction_in_tool_results(self):
        ns = self.server()
        result = ns["_sanitize"]({"local_key": KEY, "note": "contains " + KEY})
        self.assertEqual(result["local_key"], "[REDACTED]")
        self.assertNotIn(KEY, result["note"])
        result = ns["tuya_bulb_set_state"](mode="wrong " + KEY)
        self.assertFalse(result["success"])
        self.assertNotIn(KEY, result["error"])


if __name__ == "__main__":
    unittest.main()
