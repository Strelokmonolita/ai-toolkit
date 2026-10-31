"""Сбор файлов с кодом и деление на части."""

import os
from pathlib import Path

from providers import ToolkitError

SKIP_DIRS = {
    ".git", "node_modules", "venv", ".venv", "env", "__pycache__", ".idea",
    ".vscode", "dist", "build", ".mypy_cache", ".pytest_cache", "output",
}
# Файлы с секретами и шумом в нейросеть не отправляем.
SKIP_NAMES = {"package-lock.json", "yarn.lock", "poetry.lock", "config.yaml"}
BINARY_EXT = {
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp", ".pdf", ".zip",
    ".rar", ".7z", ".tar", ".gz", ".exe", ".dll", ".so", ".bin", ".pyc", ".class",
    ".jar", ".mp3", ".mp4", ".avi", ".mov", ".woff", ".woff2", ".ttf", ".eot",
    ".docx", ".xlsx", ".pptx", ".db", ".sqlite", ".o", ".obj",
}
MAX_FILE_BYTES = 500_000


def est_tokens(text):
    """Грубая оценка токенов: ~1 токен на 3 символа (с запасом)."""
    return len(text) // 3 + 1


def _is_binary(path):
    if path.suffix.lower() in BINARY_EXT:
        return True
    with open(path, "rb") as f:
        return b"\0" in f.read(4096)


def collect_files(target):
    """Возвращает (список (путь, текст), число пропущенных файлов)."""
    target = Path(target)
    if not target.exists():
        raise ToolkitError(f"Путь не найден: {target}")

    if target.is_file():
        candidates = [(target, target.name)]
    else:
        candidates = []
        for root, dirs, names in os.walk(target):
            dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
            for name in sorted(names):
                p = Path(root) / name
                candidates.append((p, p.relative_to(target).as_posix()))

    found, skipped = [], 0
    for path, rel in candidates:
        name = path.name
        if (name.startswith(".env") or name in SKIP_NAMES
                or path.stat().st_size > MAX_FILE_BYTES or _is_binary(path)):
            skipped += 1
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if text.strip():
            found.append((rel, text))
    return found, skipped


def _numbered(text):
    """Нумерует строки, чтобы нейросеть называла правильные номера."""
    lines = text.splitlines()
    return [f"{i:>4} | {line}" for i, line in enumerate(lines, 1)]


def build_chunks(files, limit):
    """Делит файлы на части не больше limit токенов. Большие файлы режет по строкам."""
    pieces = []
    for rel, text in files:
        lines = _numbered(text)
        header = f"=== ФАЙЛ: {rel} ===\n"
        cur, cur_tok = [], est_tokens(header)
        for line in lines:
            t = est_tokens(line) + 1
            if cur and cur_tok + t > limit:
                pieces.append(header + "\n".join(cur))
                header = f"=== ФАЙЛ: {rel} (продолжение) ===\n"
                cur, cur_tok = [], est_tokens(header)
            cur.append(line)
            cur_tok += t
        if cur:
            pieces.append(header + "\n".join(cur))

    chunks, cur, cur_tok = [], [], 0
    for piece in pieces:
        t = est_tokens(piece)
        if cur and cur_tok + t > limit:
            chunks.append("\n\n".join(cur))
            cur, cur_tok = [], 0
        cur.append(piece)
        cur_tok += t
    if cur:
        chunks.append("\n\n".join(cur))
    return chunks
