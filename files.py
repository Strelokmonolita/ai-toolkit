"""Сбор файлов с кодом и деление на части."""

import fnmatch
import os
import subprocess
from pathlib import Path

from providers import ToolkitError

SKIP_DIRS = {
    ".git", "node_modules", "venv", ".venv", "env", "__pycache__", ".idea",
    ".vscode", "dist", "build", ".mypy_cache", ".pytest_cache", "output",
}
# Файлы с секретами и шумом в нейросеть не отправляем. Имена сравниваются без учёта регистра.
SKIP_NAMES = {
    "package-lock.json", "yarn.lock", "poetry.lock", "config.yaml",
    "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519", "credentials.json",
    "secrets.json", ".npmrc", ".pypirc", ".netrc", ".htpasswd",
}
SECRET_EXT = {".pem", ".key", ".p12", ".pfx", ".jks", ".keystore", ".kdbx", ".env"}
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


def _is_secret(name):
    name = name.lower()
    return (name.startswith(".env") or name in SKIP_NAMES
            or Path(name).suffix in SECRET_EXT)


def _is_binary(path):
    if path.suffix.lower() in BINARY_EXT:
        return True
    with open(path, "rb") as f:
        return b"\0" in f.read(4096)


def _git(args, cwd, error):
    """Запускает git и возвращает вывод. При сбое бросает ToolkitError: error + текст от git."""
    try:
        proc = subprocess.run(["git", *args], cwd=cwd, capture_output=True,
                              text=True, encoding="utf-8", errors="replace")
    except FileNotFoundError:
        raise ToolkitError("Не найден git. Установи git или не используй --changed.")
    if proc.returncode != 0:
        raise ToolkitError(f"{error} {(proc.stderr or '').strip()}".strip())
    return proc.stdout


def changed_files(target, ref):
    """Абсолютные пути файлов, изменённых относительно ref, и новых неотслеживаемых.

    Удалённые файлы сюда попадают; их отсеивает вызывающий код.
    """
    if ref.startswith("-"):
        raise ToolkitError(f"Неверный REF для --changed: «{ref}».")
    start = target if target.is_dir() else target.parent
    top = Path(_git(["rev-parse", "--show-toplevel"], start,
                    "Папка не находится в git-репозитории.").strip())
    # -z: имена разделены нулевым байтом и не берутся в кавычки (кириллица в путях).
    diff = _git(["diff", "--name-only", "-z", ref, "--"], top,
                f"Не удалось сравнить с REF «{ref}».")
    others = _git(["ls-files", "--others", "--exclude-standard", "-z"], top,
                  "Не удалось получить список новых файлов.")
    names = {name for name in (diff + others).split("\0") if name}
    return sorted((top / name).resolve() for name in names)


def _changed_candidates(target, ref):
    """Изменённые файлы внутри target как пары (путь, имя относительно target)."""
    scope = target.resolve()
    candidates = []
    for path in changed_files(target, ref):
        if not path.is_file():  # удалённый файл
            continue
        if target.is_file():
            if path == scope:
                candidates.append((path, target.name))
            continue
        try:
            rel = path.relative_to(scope).as_posix()
        except ValueError:  # файл вне проверяемой папки
            continue
        if SKIP_DIRS.intersection(rel.split("/")[:-1]):
            continue
        candidates.append((path, rel))
    return candidates


def _excluded(rel, patterns):
    return any(fnmatch.fnmatch(rel, pattern) for pattern in patterns)


def collect_files(target, excludes=(), changed=None):
    """Возвращает (список (путь, текст), число пропущенных файлов).

    excludes - glob-шаблоны (fnmatch) относительно проверяемой папки.
    changed - git-ref: тогда берутся только файлы, изменённые относительно него.
    """
    target = Path(target)
    if not target.exists():
        raise ToolkitError(f"Путь не найден: {target}")
    patterns = [p.replace("\\", "/") for p in excludes]

    if changed is not None:
        candidates = _changed_candidates(target, changed)
    elif target.is_file():
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
        if _excluded(rel, patterns):
            skipped += 1
            continue
        if _is_secret(path.name):
            skipped += 1
            continue
        try:
            # Нечитаемый файл или битая ссылка не должны ронять всю проверку.
            if path.stat().st_size > MAX_FILE_BYTES or _is_binary(path):
                skipped += 1
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            skipped += 1
            continue
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
