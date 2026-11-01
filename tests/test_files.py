import tempfile
import unittest
from pathlib import Path

from files import build_chunks, collect_files, est_tokens
from providers import ToolkitError


class CollectFilesTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, rel, content="x = 1\n", binary=False):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if binary:
            p.write_bytes(content)
        else:
            p.write_text(content, encoding="utf-8")
        return p

    def names(self, files):
        return sorted(rel for rel, _ in files)

    def test_collects_text_files_recursively(self):
        self.write("a.py")
        self.write("pkg/b.py")
        files, skipped = collect_files(self.root)
        self.assertEqual(self.names(files), ["a.py", "pkg/b.py"])
        self.assertEqual(skipped, 0)

    def test_skips_service_dirs_secrets_and_binaries(self):
        self.write("ok.py")
        self.write(".env", "KEY=secret")
        self.write(".env.local", "KEY=secret")
        self.write("config.yaml", "a: 1")
        self.write("node_modules/lib.js")
        self.write("logo.png", b"\x89PNG", binary=True)
        self.write("data.bin2", b"ab\0cd", binary=True)
        files, skipped = collect_files(self.root)
        self.assertEqual(self.names(files), ["ok.py"])
        self.assertEqual(skipped, 5)  # .env, .env.local, config.yaml, logo.png, data.bin2

    def test_empty_files_are_ignored(self):
        self.write("empty.py", "  \n")
        files, _ = collect_files(self.root)
        self.assertEqual(files, [])

    def test_single_file_target(self):
        p = self.write("one.py", "print(1)\n")
        files, _ = collect_files(p)
        self.assertEqual(files, [("one.py", "print(1)\n")])

    def test_missing_path_raises(self):
        with self.assertRaises(ToolkitError):
            collect_files(self.root / "nope")


class ChunksTest(unittest.TestCase):
    def test_lines_are_numbered(self):
        chunks = build_chunks([("a.py", "first\nsecond\n")], 1000)
        self.assertEqual(len(chunks), 1)
        self.assertIn("=== ФАЙЛ: a.py ===", chunks[0])
        self.assertIn("   1 | first", chunks[0])
        self.assertIn("   2 | second", chunks[0])

    def test_small_files_share_one_chunk(self):
        chunks = build_chunks([("a.py", "a\n"), ("b.py", "b\n")], 1000)
        self.assertEqual(len(chunks), 1)

    def test_big_file_is_split_with_original_line_numbers(self):
        text = "\n".join(f"line number {i}" for i in range(1, 200))
        chunks = build_chunks([("big.py", text)], 200)
        self.assertGreater(len(chunks), 1)
        self.assertIn("(продолжение)", chunks[1])
        self.assertIn("| line number 199", chunks[-1])
        for c in chunks:
            self.assertLessEqual(est_tokens(c), 200 + 10)

    def test_every_line_appears_exactly_once(self):
        text = "\n".join(f"L{i}" for i in range(1, 120))
        chunks = build_chunks([("f.py", text)], 150)
        shown = [line.split("| ", 1)[1] for c in chunks for line in c.splitlines() if "| L" in line]
        self.assertEqual(shown, [f"L{i}" for i in range(1, 120)])


if __name__ == "__main__":
    unittest.main()
