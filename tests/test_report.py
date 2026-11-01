import unittest

from report import BREAKDOWN, ReviewResult, build_report, severity_rank


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


if __name__ == "__main__":
    unittest.main()
