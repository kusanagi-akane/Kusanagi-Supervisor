import ast
import json
import os
import re
import string
import unittest
from pathlib import Path

import main

ROOT = Path(__file__).resolve().parent.parent
LOCALE_DIR = ROOT / "locales"
CJK_RE = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af]")


def load_locale(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def placeholders(text):
    return {field for _, field, _, _ in string.Formatter().parse(text) if field}


class LocaleFileTests(unittest.TestCase):
    def setUp(self):
        self.base = load_locale(LOCALE_DIR / f"{main.DEFAULT_LANG}.json")
        self.locales = {p.stem: load_locale(p) for p in LOCALE_DIR.glob("*.json")}

    def test_default_locale_exists(self):
        self.assertIn(main.DEFAULT_LANG, self.locales)
        self.assertIn(main.LOG_LANG, self.locales)

    def test_all_locales_have_same_keys(self):
        base_keys = set(self.base)
        for lang, data in self.locales.items():
            with self.subTest(lang=lang):
                self.assertEqual(set(data) - base_keys, set(), "extra keys")
                self.assertEqual(base_keys - set(data), set(), "missing keys")

    def test_placeholders_match_default_locale(self):
        for lang, data in self.locales.items():
            for key, text in self.base.items():
                if key.startswith("_"):
                    continue
                with self.subTest(lang=lang, key=key):
                    self.assertEqual(placeholders(data[key]), placeholders(text))

    def test_no_reserved_placeholders(self):
        # "key" and "lang" are parameters of translate() and would clash with **kwargs
        for lang, data in self.locales.items():
            for key, text in data.items():
                if key.startswith("_"):
                    continue
                with self.subTest(lang=lang, key=key):
                    self.assertEqual(placeholders(text) & {"key", "lang"}, set())

    def test_meta_section(self):
        for lang, data in self.locales.items():
            with self.subTest(lang=lang):
                meta = data.get("_meta")
                self.assertIsInstance(meta, dict)
                self.assertTrue(meta.get("name"))

    def test_every_key_used_in_code_exists(self):
        source = (ROOT / "main.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        used = set()
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id in ("t", "translate") and node.args):
                arg = node.args[0]
                candidates = [arg.body, arg.orelse] if isinstance(arg, ast.IfExp) else [arg]
                for c in candidates:
                    if isinstance(c, ast.Constant) and isinstance(c.value, str):
                        used.add(c.value)
        self.assertTrue(used)
        self.assertEqual(used - set(self.base), set())


class NoHardcodedTextTests(unittest.TestCase):
    def test_main_has_no_cjk_string_literals(self):
        tree = ast.parse((ROOT / "main.py").read_text(encoding="utf-8"))
        offenders = [
            (node.lineno, node.value)
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and CJK_RE.search(node.value)
        ]
        self.assertEqual(offenders, [], "move these strings into locales/*.json")


class TranslateTests(unittest.TestCase):
    def setUp(self):
        self.old_lang = main.current_lang

    def tearDown(self):
        main.current_lang = self.old_lang

    def test_translate_formats_kwargs(self):
        self.assertEqual(main.translate("common.profile_not_found", lang="en", name="demo"),
                         "Script profile not found: demo")
        self.assertEqual(main.translate("common.profile_not_found", lang="zh_TW", name="demo"),
                         "找不到腳本設定：demo")

    def test_translate_falls_back_to_default_then_key(self):
        self.assertEqual(main.translate("common.yes", lang="xx"), main.translate("common.yes", lang="en"))
        self.assertEqual(main.translate("no.such.key"), "no.such.key")

    def test_translate_survives_missing_kwargs(self):
        self.assertEqual(main.translate("add.success", lang="en"), "Added script profile: {name}")

    def test_localized_text_renders_in_log_language(self):
        self.assertTrue(main.set_language("zh_TW"))
        msg = main.t("stop.not_running", name="demo")
        self.assertEqual(msg, "demo 並未在執行中")
        self.assertEqual(msg.render(main.LOG_LANG), "demo is not running")

    def test_set_language_rejects_unknown(self):
        self.assertFalse(main.set_language("xx_YY"))
        self.assertEqual(main.current_lang, self.old_lang)


class LanguageDetectionTests(unittest.TestCase):
    def test_normalize_lang_code(self):
        cases = {
            "zh_TW": "zh_TW",
            "zh-tw": "zh_TW",
            "zh_TW.UTF-8": "zh_TW",
            "Chinese (Traditional)_Taiwan": "zh_TW",
            "en_US": "en",
            "English_United States": "en",
            "C": None,
            "": None,
            None: None,
            "xx": None,
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(main.normalize_lang_code(raw), expected)

    def test_detect_language_prefers_cli_argument(self):
        self.assertEqual(main.detect_language(["--lang", "zh-TW"]), "zh_TW")
        self.assertEqual(main.detect_language(["--lang=en"]), "en")

    def test_detect_language_defaults_to_english(self):
        old = os.environ.pop(main.LANG_ENV_VAR, None)
        try:
            self.assertEqual(main.detect_language([]), "en")
            os.environ[main.LANG_ENV_VAR] = "zh_TW"
            self.assertEqual(main.detect_language([]), "zh_TW")
        finally:
            os.environ.pop(main.LANG_ENV_VAR, None)
            if old is not None:
                os.environ[main.LANG_ENV_VAR] = old


class BoolWordsTests(unittest.TestCase):
    def test_coerce_bool_accepts_words_from_all_locales(self):
        self.assertTrue(main.coerce_bool("是", False))
        self.assertTrue(main.coerce_bool("啟用", False))
        self.assertFalse(main.coerce_bool("停用", True))
        self.assertTrue(main.coerce_bool("YES", False))
        self.assertFalse(main.coerce_bool("off", True))
        self.assertTrue(main.coerce_bool("maybe", True))


if __name__ == "__main__":
    unittest.main()
