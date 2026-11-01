import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import toolkit
from providers import ToolkitError
from tests.test_review import FakeProvider

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


CONFIG = """default_profile: a
profiles:
  a:
    type: openai
    base_url: https://a.example.com
    key_env: KEY_A
    model: m1
  b:
    type: openai
    base_url: https://b.example.com
    key_env: KEY_B
    model: m2
"""


class CliTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.config = self.dir / "config.yaml"
        self.config.write_text(CONFIG, encoding="utf-8")
        self.code_dir = self.dir / "empty_project"
        self.code_dir.mkdir()
        (self.code_dir / "__init__.py").write_text("", encoding="utf-8")

    def run_main(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        code = 0
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                toolkit.main(list(argv))
            except SystemExit as exc:
                code = exc.code
        return code, out.getvalue(), err.getvalue()

    def test_version(self):
        code, out, _ = self.run_main("--version")
        self.assertEqual(code, 0)
        self.assertIn("0.2.0", out)

    def test_profiles_lists_profiles_from_config(self):
        code, out, _ = self.run_main("--config", str(self.config), "profiles")
        self.assertEqual(code, 0)
        self.assertIn("a (по умолчанию): type=openai, model=m1", out)
        self.assertIn("b: type=openai, model=m2", out)

    def test_profile_before_subcommand_with_review(self):
        env = {"KEY_A": "ka", "KEY_B": "kb"}
        with mock.patch.dict(os.environ, env), mock.patch("toolkit.create_provider") as create:
            code, out, _ = self.run_main("--config", str(self.config), "--profile", "b",
                                         "review", str(self.code_dir))
        self.assertEqual(code, 1)
        self.assertIn("Профиль: b, модель: m2", out)
        self.assertEqual(create.call_args[0][0]["model"], "m2")

    def test_profile_and_config_after_review(self):
        env = {"KEY_A": "ka", "KEY_B": "kb"}
        with mock.patch.dict(os.environ, env), mock.patch("toolkit.create_provider") as create:
            code, out, _ = self.run_main("review", str(self.code_dir),
                                         "--profile", "b", "--config", str(self.config))
        self.assertEqual(code, 1)
        self.assertIn("Профиль: b, модель: m2", out)
        self.assertEqual(create.call_args[0][0]["model"], "m2")

    def test_empty_folder_gives_clear_error_and_exit_1(self):
        env = {"KEY_A": "ka"}
        with mock.patch.dict(os.environ, env), mock.patch("toolkit.create_provider"):
            code, _, err = self.run_main("--config", str(self.config), "review", str(self.code_dir))
        self.assertEqual(code, 1)
        self.assertIn("Ошибка:", err)
        self.assertNotIn("Traceback", err)

    def test_bad_fail_on_value_gives_1(self):
        code, _, err = self.run_main("--config", str(self.config), "review", str(self.code_dir),
                                     "--fail-on", "critical")
        self.assertEqual(code, 1)
        self.assertIn("critical", err)

    def test_bad_format_value_gives_1(self):
        code, _, err = self.run_main("--config", str(self.config), "review", str(self.code_dir),
                                     "--format", "xml")
        self.assertEqual(code, 1)
        self.assertIn("xml", err)

    def test_unknown_flag_gives_1(self):
        code, _, _ = self.run_main("--config", str(self.config), "review", str(self.code_dir),
                                   "--nope")
        self.assertEqual(code, 1)


class ReviewFlagsTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.config = self.dir / "config.yaml"
        self.config.write_text(CONFIG, encoding="utf-8")
        self.project = self.dir / "project"
        self.project.mkdir()
        (self.project / "src.py").write_text("x = 1\n", encoding="utf-8")
        self.env = mock.patch.dict(os.environ, {"KEY_A": "ka"})
        self.env.start()
        self.addCleanup(self.env.stop)

    def run_review(self, provider, *argv):
        out, err = io.StringIO(), io.StringIO()
        code = 0
        with mock.patch("toolkit.create_provider", return_value=provider), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                toolkit.main(["--config", str(self.config), "review", str(self.project), *argv])
            except SystemExit as exc:
                code = exc.code
        return code, out.getvalue(), err.getvalue()

    def test_yes_flag_skips_input(self):
        provider = FakeProvider(["ПРОБЛЕМ НЕТ"])
        report = self.dir / "report.md"
        with mock.patch("builtins.input", side_effect=AssertionError("input() вызван")) as ask:
            code, _, _ = self.run_review(provider, "-y", "--output", str(report))
        self.assertEqual(code, 0)
        ask.assert_not_called()
        self.assertEqual(len(provider.calls), 1)
        self.assertTrue(report.exists())

    def test_output_to_file_path(self):
        report = self.dir / "custom" / "my_report.md"
        code, _, _ = self.run_review(FakeProvider(["ПРОБЛЕМ НЕТ"]),
                                     "-y", "--output", str(report))
        self.assertEqual(code, 0)
        self.assertTrue(report.is_file())
        self.assertIn("Проблем в таблице нет.", report.read_text(encoding="utf-8"))

    def test_output_to_existing_directory(self):
        folder = self.dir / "reports"
        folder.mkdir()
        code, _, _ = self.run_review(FakeProvider(["ПРОБЛЕМ НЕТ"]),
                                     "-y", "--output", str(folder))
        self.assertEqual(code, 0)
        self.assertTrue((folder / "review_report.md").is_file())

    def test_format_json_is_valid(self):
        row = "Высокая | src.py | 1 | баг | фикс"
        report = self.dir / "report.json"
        code, _, _ = self.run_review(FakeProvider([row]), "-y", "--format", "json",
                                     "--output", str(report))
        self.assertEqual(code, 0)
        data = json.loads(report.read_text(encoding="utf-8"))
        self.assertIn("issues", data)

    def test_json_has_severity_code_and_int_line(self):
        report = self.dir / "report.json"
        self.run_review(FakeProvider(["Средняя | src.py | 1 | баг | фикс"]),
                        "-y", "--format", "json", "--output", str(report))
        issue = json.loads(report.read_text(encoding="utf-8"))["issues"][0]
        self.assertEqual(issue["severity"], "medium")
        self.assertEqual(issue["line"], 1)

    def test_fail_on_gives_2_when_level_found(self):
        out_file = str(self.dir / "r.md")
        code, _, _ = self.run_review(FakeProvider(["Высокая | src.py | 1 | баг | фикс"]),
                                     "-y", "--fail-on", "high", "--output", out_file)
        self.assertEqual(code, 2)

    def test_fail_on_counts_higher_levels(self):
        out_file = str(self.dir / "r.md")
        code, _, _ = self.run_review(FakeProvider(["средняя | src.py | 1 | баг | фикс"]),
                                     "-y", "--fail-on", "medium", "--output", out_file)
        self.assertEqual(code, 2)

    def test_fail_on_ignores_lower_levels(self):
        out_file = str(self.dir / "r.md")
        code, _, _ = self.run_review(FakeProvider(["Низкая | src.py | 1 | стиль | фикс"]),
                                     "-y", "--fail-on", "medium", "--output", out_file)
        self.assertEqual(code, 0)

    def test_no_fail_on_gives_0_with_findings(self):
        out_file = str(self.dir / "r.md")
        code, _, _ = self.run_review(FakeProvider(["Высокая | src.py | 1 | баг | фикс"]),
                                     "-y", "--output", out_file)
        self.assertEqual(code, 0)

    def test_program_error_gives_1_even_with_fail_on(self):
        provider = mock.Mock(model="m", max_output_tokens=4096)
        provider.send.side_effect = ToolkitError("сеть недоступна")
        out_file = str(self.dir / "r.md")
        code, _, err = self.run_review(provider, "-y", "--fail-on", "low", "--output", out_file)
        self.assertEqual(code, 1)
        self.assertIn("Ошибка:", err)


if __name__ == "__main__":
    unittest.main()
