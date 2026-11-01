import json
import unittest

from report import (BREAKDOWN, ReviewResult, build_json, build_report, has_findings_at_or_above,
                    line_number, normalize_severity, severity_code, severity_rank)


def make(**over):
    return ReviewResult(**{"profile": "p", "model": "m", "target": "t", "n_chunks": 1, **over})


class SeverityRankTest(unittest.TestCase):
    def test_order_and_unknown(self):
        ranks = [severity_rank(s) for s in ("Высокая", "средняя", "НИЗКАЯ", "что-то")]
        self.assertEqual(ranks, [0, 1, 2, 3])


class BuildReportTest(unittest.TestCase):
    def test_sorted_by_severity(self):
        result = make(rows=[("Низкая", "a", "1", "p3", "f"), ("Высокая", "a", "2", "p1", "f"),
                            ("Средняя", "a", "3", "p2", "f")])
        md = build_report(result)
        self.assertLess(md.index("p1"), md.index("p2"))
        self.assertLess(md.index("p2"), md.index("p3"))

    def test_pipe_in_cell_is_escaped(self):
        md = build_report(make(rows=[("Высокая", "a", "1", "x | y", "f")]))
        self.assertIn("x \\| y", md)

    def test_no_rows_message_and_errors(self):
        md = build_report(make(errors=["Часть 1: сбой"]))
        self.assertIn("Проблем в таблице нет.", md)
        self.assertIn("## Проверка прервана", md)

    def test_raw_block_is_included(self):
        md = build_report(make(raw_blocks=[(1, "свободный текст")]))
        self.assertIn("свободный текст", md)

    def test_warnings_section(self):
        md = build_report(make(warnings=["Часть 1: оборван"]))
        self.assertIn("## Предупреждения", md)

    def test_breakdown_only_when_reported(self):
        self.assertNotIn("Разбивка", build_report(make()))
        result = make()
        result.usage["cache_read_input_tokens"] = 5
        md = build_report(result)
        self.assertIn("Разбивка", md)
        self.assertIn(BREAKDOWN["cache_read_input_tokens"], md)

    def test_usage_is_not_shared_between_results(self):
        a, b = make(), make()
        a.usage["input"] = 99
        self.assertEqual(b.usage["input"], 0)


class SeverityCodeTest(unittest.TestCase):
    def test_russian_any_case(self):
        for raw in ("Высокая", "ВЫСОКАЯ", "высокий", " Средняя ", "Средний", "низкая"):
            self.assertIn(normalize_severity(raw), ("high", "medium", "low"), raw)
        self.assertEqual(normalize_severity("ВЫСОКАЯ"), "high")
        self.assertEqual(normalize_severity("Средняя"), "medium")
        self.assertEqual(normalize_severity("низкая"), "low")

    def test_english_variants(self):
        self.assertEqual(normalize_severity("High"), "high")
        self.assertEqual(normalize_severity("MEDIUM"), "medium")
        self.assertEqual(normalize_severity("med"), "medium")
        self.assertEqual(normalize_severity("low"), "low")

    def test_unknown_is_none(self):
        self.assertIsNone(normalize_severity("critical"))
        self.assertIsNone(normalize_severity(""))
        self.assertEqual(severity_code("critical"), "critical")

    def test_rank_accepts_codes_and_russian(self):
        self.assertEqual([severity_rank(s) for s in ("high", "medium", "low", "Высокая")],
                         [0, 1, 2, 0])


class LineNumberTest(unittest.TestCase):
    def test_numbers(self):
        self.assertEqual(line_number("12"), 12)
        self.assertEqual(line_number(" 7 "), 7)

    def test_not_a_number_is_none(self):
        for bad in ("", "12-15", "L12", "строка 3", "-1", "1.5"):
            self.assertIsNone(line_number(bad), bad)


class HasFindingsTest(unittest.TestCase):
    rows = [("medium", "a", "1", "p", "f"), ("low", "a", "2", "p", "f")]

    def test_levels_include_higher(self):
        self.assertFalse(has_findings_at_or_above(self.rows, "high"))
        self.assertTrue(has_findings_at_or_above(self.rows, "medium"))
        self.assertTrue(has_findings_at_or_above(self.rows, "low"))

    def test_no_rows(self):
        self.assertFalse(has_findings_at_or_above([], "low"))

    def test_unknown_severity_is_not_counted(self):
        self.assertFalse(has_findings_at_or_above([("что-то", "a", "1", "p", "f")], "low"))


class ReportOutputTest(unittest.TestCase):
    def test_markdown_shows_russian_labels(self):
        md = build_report(make(rows=[("high", "a", "1", "p1", "f"), ("low", "a", "2", "p2", "f")]))
        self.assertIn("| Высокая | a | 1 | p1 | f |", md)
        self.assertIn("| Низкая | a | 2 | p2 | f |", md)
        self.assertNotIn("| high |", md)

    def test_markdown_keeps_unknown_severity_text(self):
        md = build_report(make(rows=[("critical", "a", "1", "p", "f")]))
        self.assertIn("| critical | a | 1 | p | f |", md)

    def test_json_uses_codes_and_int_line(self):
        rows = [("Средняя", "a.py", "12", "p1", "f"), ("High", "b.py", "12-15", "p2", "f")]
        data = json.loads(build_json(make(rows=rows)))
        self.assertEqual(data["issues"][0], {"severity": "high", "file": "b.py", "line": None,
                                             "problem": "p2", "fix": "f"})
        self.assertEqual(data["issues"][1]["severity"], "medium")
        self.assertEqual(data["issues"][1]["line"], 12)
        self.assertIsInstance(data["issues"][1]["line"], int)


if __name__ == "__main__":
    unittest.main()
