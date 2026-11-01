import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import review
from providers import ToolkitError
from providers.base import Provider, Reply
from report import ReviewResult

SETTINGS = {"chunk_tokens": 30000, "max_output_tokens": 4096, "timeout_seconds": 120}


class FakeProvider(Provider):
    """Отвечает заготовленными текстами по очереди, без сети."""

    def __init__(self, replies):
        super().__init__("http://fake", None, "fake-model", 100, 10)
        self.replies = list(replies)
        self.calls = []

    def send(self, system, messages):
        self.calls.append(messages)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        if isinstance(reply, Reply):
            return reply
        return Reply(reply, {"input": 10, "output": 5})


class ParseResponseTest(unittest.TestCase):
    def test_parses_rows(self):
        text = "Высокая | a.py | 14 | SQL-инъекция | параметры запроса\nНизкая | b.py | 3 | x | y"
        rows = review.parse_response(text)
        self.assertEqual(rows[0], ("high", "a.py", "14", "SQL-инъекция", "параметры запроса"))
        self.assertEqual(len(rows), 2)

    def test_strips_bullets_and_backticks(self):
        rows = review.parse_response("- Средняя | a.py | 1 | проблема | фикс")
        self.assertEqual(rows[0][0], "medium")

    def test_pipe_inside_problem_is_kept(self):
        rows = review.parse_response("Высокая | a.py | 2 | a | b ошибка | исправить")
        self.assertEqual(rows[0][3], "a | b ошибка")
        self.assertEqual(rows[0][4], "исправить")

    def test_skips_table_header(self):
        text = "Важность | Файл | Строка | Проблема | Исправление"
        self.assertEqual(review.parse_response(text), [])

    def test_skips_table_separator(self):
        for sep in ("--- | --- | --- | --- | ---", "|---|---|---|---|---|", "|:--|:-:|--:|---|---|"):
            self.assertEqual(review.parse_response(sep), [], sep)

    def test_markdown_table_with_outer_pipes(self):
        rows = review.parse_response("| Высокая | a.py | 5 | баг | фикс |")
        self.assertEqual(rows, [("high", "a.py", "5", "баг", "фикс")])

    def test_malformed_row_is_reported_not_dropped(self):
        rows, malformed = review.split_response(
            "Высокая | a.py | 5 | баг | фикс\nСредняя | b.py | 7 | без исправления")
        self.assertEqual(len(rows), 1)
        self.assertEqual(malformed, ["Средняя | b.py | 7 | без исправления"])

    def test_dedupe_ignores_case_spaces_and_fix_text(self):
        rows = [("Высокая", "a.py", "5", "SQL  инъекция", "один"),
                ("Средняя", "A.py", "5", "sql инъекция", "другой"),
                ("Высокая", "a.py", "6", "SQL инъекция", "один")]
        self.assertEqual(len(review.dedupe(rows)), 2)

    def test_ignores_free_text(self):
        self.assertEqual(review.parse_response("Вот мой ответ без таблицы"), [])


class ReviewChunksTest(unittest.TestCase):
    def test_collects_rows_usage_and_logs_progress(self):
        logs = []
        provider = FakeProvider(["Высокая | a.py | 1 | баг | фикс", "ПРОБЛЕМ НЕТ"])
        result = review.review_chunks(provider, "prof", "t", ["a", "b"], log=logs.append)
        self.assertEqual(result.rows, [("high", "a.py", "1", "баг", "фикс")])
        self.assertEqual((result.usage["input"], result.usage["output"]), (20, 10))
        self.assertEqual((result.profile, result.model, result.n_chunks), ("prof", "fake-model", 2))
        self.assertEqual(logs, ["Часть 1 из 2...", "Часть 2 из 2..."])

    def test_provider_error_is_recorded_and_stops(self):
        provider = FakeProvider(["Высокая | a.py | 1 | баг | фикс", ToolkitError("сбой"), "ПРОБЛЕМ НЕТ"])
        result = review.review_chunks(provider, "p", "t", ["a", "b", "c"])
        self.assertEqual(len(result.rows), 1)
        self.assertEqual(result.errors, ["Часть 2: сбой"])
        self.assertEqual(len(provider.calls), 2)

    def test_off_format_and_truncated(self):
        provider = FakeProvider(["просто текст",
                                 Reply("ПРОБЛЕМ НЕТ", {"input": 1, "output": 1}, truncated=True)])
        result = review.review_chunks(provider, "p", "t", ["a", "b"])
        self.assertEqual(result.raw_blocks, [(1, "просто текст")])
        self.assertEqual(len(result.warnings), 1)

    def test_dedupes_across_chunks(self):
        row = "Высокая | a.py | 1 | баг | фикс"
        result = review.review_chunks(FakeProvider([row, row]), "p", "t", ["a", "b"])
        self.assertEqual(len(result.rows), 1)


class SaveReportTest(unittest.TestCase):
    def test_writes_file_and_creates_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = ReviewResult("p", "m", "t", 1, rows=[("Высокая", "a", "1", "x", "y")])
            path = review.save_report(result, Path(tmp) / "sub")
            self.assertEqual(path.name, review.REPORT_NAME)
            self.assertIn("| Высокая | a | 1 | x | y |", path.read_text(encoding="utf-8"))

    def test_os_error_becomes_toolkit_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            blocker = Path(tmp) / "f"
            blocker.write_text("x", encoding="utf-8")
            with self.assertRaises(ToolkitError):
                review.save_report(ReviewResult("p", "m", "t", 1), blocker)


class RunReviewTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.src = self.root / "src.py"
        self.src.write_text("x = 1\n", encoding="utf-8")
        self.out = self.root / "out"

    def tearDown(self):
        self._tmp.cleanup()

    def run_review(self, provider, answer="y"):
        with mock.patch("builtins.input", return_value=answer), \
                contextlib.redirect_stdout(io.StringIO()):
            review.run_review(provider, "prof", str(self.src), SETTINGS, self.out)

    def report(self):
        return (self.out / "review_report.md").read_text(encoding="utf-8")

    def test_writes_report(self):
        provider = FakeProvider(["Высокая | src.py | 1 | баг | исправить"])
        self.run_review(provider)
        self.assertIn("| Высокая | src.py | 1 | баг | исправить |", self.report())

    def test_user_can_cancel(self):
        provider = FakeProvider([])
        self.run_review(provider, answer="n")
        self.assertEqual(provider.calls, [])
        self.assertFalse((self.out / "review_report.md").exists())

    def test_no_problems_reply(self):
        self.run_review(FakeProvider(["ПРОБЛЕМ НЕТ"]))
        report = self.report()
        self.assertIn("Проблем в таблице нет.", report)
        self.assertNotIn("другом формате", report)

    def test_off_format_reply_goes_to_raw_block(self):
        self.run_review(FakeProvider(["Код выглядит нормально, но я не уверен"]))
        self.assertIn("другом формате", self.report())

    def test_provider_error_saves_partial_report_and_raises(self):
        provider = FakeProvider([ToolkitError("сбой сети")])
        with self.assertRaises(ToolkitError):
            self.run_review(provider)
        self.assertIn("Проверка прервана", self.report())

    def test_truncated_reply_adds_warning(self):
        provider = FakeProvider([Reply("Высокая | src.py | 1 | баг | фикс",
                                       {"input": 1, "output": 1}, truncated=True)])
        self.run_review(provider)
        report = self.report()
        self.assertIn("## Предупреждения", report)
        self.assertIn("max_output_tokens", report)

    def test_malformed_lines_land_in_raw_block(self):
        self.run_review(FakeProvider(["Высокая | src.py | 1 | баг | фикс\nСредняя | src.py | 2 | без фикса"]))
        report = self.report()
        self.assertIn("| Высокая | src.py | 1 | баг | фикс |", report)
        self.assertIn("Средняя | src.py | 2 | без фикса", report)

    def test_duplicates_across_chunks_are_merged(self):
        row = "Высокая | src.py | 1 | баг | фикс"
        with mock.patch("review.build_chunks", return_value=["a", "b"]):
            self.run_review(FakeProvider([row, row]))
        self.assertEqual(self.report().count("| Высокая | src.py | 1 | баг | фикс |"), 1)

    def test_closed_stdin_cancels_without_sending(self):
        provider = FakeProvider([])
        with mock.patch("builtins.input", side_effect=EOFError), \
                contextlib.redirect_stdout(io.StringIO()):
            review.run_review(provider, "prof", str(self.src), SETTINGS, self.out)
        self.assertEqual(provider.calls, [])

    def test_report_write_failure_is_toolkit_error(self):
        blocker = self.root / "blocker"
        blocker.write_text("файл на месте папки", encoding="utf-8")
        with mock.patch("builtins.input", return_value="y"), \
                contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(ToolkitError):
                review.run_review(FakeProvider(["ПРОБЛЕМ НЕТ"]), "p", str(self.src),
                                  SETTINGS, blocker)

    def test_no_text_files_raises(self):
        empty = self.root / "empty_dir"
        empty.mkdir()
        with self.assertRaises(ToolkitError):
            review.run_review(FakeProvider([]), "p", str(empty), SETTINGS, self.out)


if __name__ == "__main__":
    unittest.main()
