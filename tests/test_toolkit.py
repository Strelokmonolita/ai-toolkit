import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import toolkit
from providers import ToolkitError

PROFILE = {"type": "openai", "base_url": "https://api.example.com", "key_env": "TEST_KEY",
           "model": "m"}


class GetProfileTest(unittest.TestCase):
    def cfg(self, **over):
        return {"profiles": {"p": {**PROFILE, **over}}}

    def test_valid_profile(self):
        self.assertEqual(toolkit.get_profile(self.cfg(), "p")["model"], "m")

    def test_unknown_profile_lists_available(self):
        with self.assertRaisesRegex(ToolkitError, "Есть: p"):
            toolkit.get_profile(self.cfg(), "other")

    def test_missing_field(self):
        with self.assertRaisesRegex(ToolkitError, "model"):
            toolkit.get_profile(self.cfg(model=""), "p")

    def test_bad_type(self):
        with self.assertRaisesRegex(ToolkitError, "type"):
            toolkit.get_profile(self.cfg(type="gemini"), "p")

    def test_bad_url(self):
        with self.assertRaisesRegex(ToolkitError, "base_url"):
            toolkit.get_profile(self.cfg(base_url="api.example.com"), "p")

    def test_empty_profile_body(self):
        with self.assertRaisesRegex(ToolkitError, "должен содержать"):
            toolkit.get_profile({"profiles": {"p": None}}, "p")

    def test_url_is_stripped(self):
        p = toolkit.get_profile(self.cfg(base_url="  https://a.b  "), "p")
        self.assertEqual(p["base_url"], "https://a.b")


class GetKeyTest(unittest.TestCase):
    def test_none_means_no_key(self):
        self.assertIsNone(toolkit.get_key({"key_env": "NONE"}))

    def test_reads_env(self):
        with mock.patch.dict(os.environ, {"TEST_KEY": " abc "}):
            self.assertEqual(toolkit.get_key(PROFILE), "abc")

    def test_missing_key(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("TEST_KEY", None)
            with self.assertRaisesRegex(ToolkitError, "TEST_KEY"):
                toolkit.get_key(PROFILE)


class PositiveIntTest(unittest.TestCase):
    def test_ok(self):
        self.assertEqual(toolkit.positive_int({"a": "5"}, "a"), 5)

    def test_rejects_zero_negative_and_text(self):
        for bad in (0, -1, "abc", None):
            with self.assertRaises(ToolkitError):
                toolkit.positive_int({"a": bad}, "a")


class LoadConfigTest(unittest.TestCase):
    def load(self, text):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "config.yaml"
            if text is not None:
                p.write_text(text, encoding="utf-8")
            return toolkit.load_config(p)

    def test_missing_file(self):
        with self.assertRaisesRegex(ToolkitError, "config.example.yaml"):
            self.load(None)

    def test_broken_yaml(self):
        with self.assertRaisesRegex(ToolkitError, "отступы"):
            self.load("profiles: [unclosed")

    def test_no_profiles(self):
        with self.assertRaisesRegex(ToolkitError, "profiles"):
            self.load("settings: {}")

    def test_ok(self):
        cfg = self.load("profiles:\n  a:\n    type: openai\n")
        self.assertIn("a", cfg["profiles"])


if __name__ == "__main__":
    unittest.main()
