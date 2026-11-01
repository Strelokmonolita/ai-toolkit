import contextlib
import io
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import files
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

    def test_exclude_all_without_changed_is_error_1(self):
        provider = FakeProvider(["ПРОБЛЕМ НЕТ"])
        code, _, err = self.run_review(provider, "--exclude", "*.py", "-y")
        self.assertEqual(code, 1)
        self.assertIn("нет текстовых файлов", err)
        self.assertEqual(provider.calls, [])

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


class CollectFilesTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def write(self, rel, text="x = 1\n"):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def fake_git(self, diff="", others="", rev_code=0, diff_code=0):
        def run(cmd, **kwargs):
            if "rev-parse" in cmd:
                return subprocess.CompletedProcess(cmd, rev_code, f"{self.root}\n", "fatal: нет репо")
            if "diff" in cmd:
                return subprocess.CompletedProcess(cmd, diff_code, diff, "fatal: bad revision")
            return subprocess.CompletedProcess(cmd, 0, others, "")
        return mock.patch("files.subprocess.run", side_effect=run)

    def test_exclude_patterns_count_as_skipped(self):
        self.write("src/a.py")
        self.write("tests/test_a.py")
        self.write("b.log")
        found, skipped = files.collect_files(self.root, excludes=["tests/*", "*.log"])
        self.assertEqual({rel for rel, _ in found}, {"src/a.py"})
        self.assertEqual(skipped, 2)

    def test_exclude_folder_with_or_without_slash(self):
        self.write("tests/a.py")
        self.write("tests/sub/b.py")
        self.write("src/a.py")
        for pattern in ("tests", "tests/"):
            found, skipped = files.collect_files(self.root, excludes=[pattern])
            self.assertEqual({rel for rel, _ in found}, {"src/a.py"}, pattern)
            self.assertEqual(skipped, 2, pattern)

    def test_exclude_accepts_backslash_pattern(self):
        self.write("tests/test_a.py")
        self.write("src/a.py")
        found, _ = files.collect_files(self.root, excludes=["tests\\*"])
        self.assertEqual({rel for rel, _ in found}, {"src/a.py"})

    def test_changed_uses_diff_and_untracked_and_skips_deleted(self):
        for rel in ("changed.py", "sub/x.py", "new.py", "other/o.py"):
            self.write(rel)
        with self.fake_git(diff="changed.py\0sub/x.py\0gone.py\0", others="new.py\0"):
            found, skipped = files.collect_files(self.root, changed="HEAD")
        self.assertEqual({rel for rel, _ in found}, {"changed.py", "sub/x.py", "new.py"})
        self.assertEqual(skipped, 0)

    def test_changed_limited_to_target_folder(self):
        self.write("sub/x.py")
        self.write("changed.py")
        with self.fake_git(diff="sub/x.py\0changed.py\0"):
            found, _ = files.collect_files(self.root / "sub", changed="HEAD")
        self.assertEqual([rel for rel, _ in found], ["x.py"])

    def test_changed_applies_exclude_and_text_filter(self):
        self.write("a.py")
        self.write("b.log")
        self.write("img.bin", "\0\1")
        with self.fake_git(diff="a.py\0b.log\0img.bin\0"):
            found, skipped = files.collect_files(self.root, excludes=["*.log"], changed="HEAD")
        self.assertEqual([rel for rel, _ in found], ["a.py"])
        self.assertEqual(skipped, 2)

    def test_not_git_repo_is_error(self):
        self.write("a.py")
        with self.fake_git(rev_code=128):
            with self.assertRaisesRegex(ToolkitError, "git-репозитории"):
                files.collect_files(self.root, changed="HEAD")

    def test_bad_ref_is_error(self):
        self.write("a.py")
        with self.fake_git(diff_code=128):
            with self.assertRaisesRegex(ToolkitError, "nope"):
                files.collect_files(self.root, changed="nope")

    def test_ref_starting_with_dash_is_refused_without_git(self):
        with mock.patch("files.subprocess.run") as run:
            with self.assertRaises(ToolkitError):
                files.collect_files(self.root, changed="--output=x")
        run.assert_not_called()

    def test_missing_git_is_error(self):
        with mock.patch("files.subprocess.run", side_effect=FileNotFoundError):
            with self.assertRaisesRegex(ToolkitError, "git"):
                files.collect_files(self.root, changed="HEAD")


def run_main_for_flags(*argv):
    out, err = io.StringIO(), io.StringIO()
    code = 0
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            toolkit.main(list(argv))
        except SystemExit as exc:
            code = exc.code
    return code, out.getvalue(), err.getvalue()


class ChangedFlagTest(unittest.TestCase):
    def test_flags_parse(self):
        args = toolkit.build_parser().parse_args(
            ["review", "p", "--exclude", "a", "--exclude", "b", "--changed", "--base", "main"])
        self.assertEqual(args.exclude, ["a", "b"])
        self.assertTrue(args.changed)
        self.assertEqual(args.base, "main")
        plain = toolkit.build_parser().parse_args(["review", "p"])
        self.assertFalse(plain.changed)
        self.assertIsNone(plain.base)

    def test_changed_before_path_does_not_eat_path(self):
        args = toolkit.build_parser().parse_args(["review", "--changed", "./proj"])
        self.assertEqual(args.path, "./proj")
        self.assertTrue(args.changed)

    def test_base_without_changed_is_exit_1(self):
        code, _, err = run_main_for_flags("review", "p", "--base", "main")
        self.assertEqual(code, 1)
        self.assertIn("--changed", err)

    def test_no_changed_files_prints_message_and_exit_0(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        config = root / "config.yaml"
        config.write_text(CONFIG, encoding="utf-8")
        project = root / "project"
        project.mkdir()
        (project / "src.py").write_text("x = 1\n", encoding="utf-8")
        provider = FakeProvider(["ПРОБЛЕМ НЕТ"])

        def run(cmd, **kwargs):
            out = f"{root}\n" if "rev-parse" in cmd else ""
            return subprocess.CompletedProcess(cmd, 0, out, "")

        out = io.StringIO()
        with mock.patch.dict(os.environ, {"KEY_A": "ka"}), \
                mock.patch("files.subprocess.run", side_effect=run), \
                mock.patch("toolkit.create_provider", return_value=provider), \
                contextlib.redirect_stdout(out):
            toolkit.main(["--config", str(config), "review", str(project), "--changed"])
        self.assertIn("Нет изменённых файлов", out.getvalue())
        self.assertEqual(provider.calls, [])


if __name__ == "__main__":
    unittest.main()
