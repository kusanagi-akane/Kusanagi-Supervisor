import tempfile
import unittest
from pathlib import Path

import main


class ConfigNormalizationTests(unittest.TestCase):
    def test_normalize_configs_applies_defaults_and_coercions(self):
        data = {
            " demo ": {
                "path": 123,
                "file": "",
                "enabled": "no",
                "auto_restart": "yes",
                "args": "--debug --port 8080",
                "env": {"COUNT": 3},
            }
        }

        normalized = main.normalize_configs(data)
        conf = normalized["demo"]

        self.assertEqual(conf["path"], "123")
        self.assertEqual(conf["file"], "main.py")
        self.assertFalse(conf["enabled"])
        self.assertTrue(conf["auto_restart"])
        self.assertEqual(conf["args"], ["--debug", "--port", "8080"])
        self.assertEqual(conf["env"], {"COUNT": "3"})

    def test_normalize_configs_rejects_non_object_root(self):
        with self.assertRaises(ValueError):
            main.normalize_configs([])

    def test_save_and_load_configs_round_trip(self):
        old_path = main.CONFIG_PATH
        old_configs = main.SCRIPT_CONFIGS.copy()

        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmpdir:
            try:
                main.CONFIG_PATH = Path(tmpdir) / "supervisor_config.json"
                main.SCRIPT_CONFIGS = {
                    "demo": {
                        "path": ".",
                        "file": "script.py",
                        "enabled": True,
                        "auto_restart": False,
                        "args": ["--once"],
                        "env": {"MODE": "test"},
                    }
                }

                self.assertTrue(main.save_configs())
                main.SCRIPT_CONFIGS = {}
                self.assertTrue(main.load_configs())
                self.assertEqual(main.SCRIPT_CONFIGS["demo"]["file"], "script.py")
                self.assertEqual(main.SCRIPT_CONFIGS["demo"]["env"], {"MODE": "test"})
            finally:
                main.CONFIG_PATH = old_path
                main.SCRIPT_CONFIGS = old_configs


class RestartLimitTests(unittest.TestCase):
    def test_restart_limit_blocks_after_window_capacity(self):
        old_limit = main.RESTART_LIMIT
        old_window = main.RESTART_WINDOW

        try:
            main.RESTART_LIMIT = 2
            main.RESTART_WINDOW = 60
            with main.state_lock:
                main.restart_history.clear()

            self.assertFalse(main.is_restart_limited("demo"))
            self.assertFalse(main.is_restart_limited("demo"))
            self.assertTrue(main.is_restart_limited("demo"))
        finally:
            main.RESTART_LIMIT = old_limit
            main.RESTART_WINDOW = old_window
            with main.state_lock:
                main.restart_history.clear()


if __name__ == "__main__":
    unittest.main()
