"""Команда review: проверка кода нейросетью и отчёт review_report.md."""

import re
from datetime import datetime
from pathlib import Path

from files import build_chunks, collect_files, est_tokens
from providers import ToolkitError

SYSTEM = (
    "Ты опытный ревьюер кода. Найди реальные проблемы: баги, уязвимости, "
    "опасные места, ошибки логики. Мелкие придирки к стилю не нужны. "
    "Строки кода пронумерованы в виде '  12 | код': используй эти номера.\n"
    "Отвечай ТОЛЬКО строками такого формата, по одной проблеме на строку:\n"
    "ВАЖНОСТЬ | файл | строка | проблема | исправление\n"
    "ВАЖНОСТЬ - одно из слов: Высокая, Средняя, Низкая. "
    "Пиши по-русски. Без вступлений, без markdown, без нумерации. "
    "Если проблем нет, ответь одной строкой: ПРОБЛЕМ НЕТ"
)
RANK = {"выс": 0, "сред": 1, "низ": 2}
# Доп. поля usage есть только у провайдера anthropic.
BREAKDOWN = {
    "input_tokens": "input_tokens (обычные)",
    "cache_creation_input_tokens": "cache_creation_input_tokens (запись в кэш)",
    "cache_read_input_tokens": "cache_read_input_tokens (чтение из кэша)",
}


def parse_response(text):
    """Достаёт строки таблицы из ответа. Возвращает список (важность, файл, строка, проблема, исправление)."""
    rows = []
    for line in text.splitlines():
        line = line.strip().lstrip("-*• ").strip("`")
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 5:
            continue
        sev, file_, lineno = parts[0], parts[1], parts[2]
        fix = parts[-1]
        problem = " | ".join(parts[3:-1])
        if sev.lower().startswith(("важность", "---")):  # заголовок таблицы
            continue
        rows.append((sev, file_, lineno, problem, fix))
    return rows


def _cell(s):
    return s.replace("|", "\\|").replace("\n", " ")


def _rank(sev):
    s = sev.lower()
    for key, val in RANK.items():
        if s.startswith(key):
            return val
    return 3


def build_report(profile, model, target, rows, raw_blocks, errors, usage, n_chunks):
    out = [
        "# Отчёт о проверке кода",
        "",
        f"- Дата: {datetime.now():%Y-%m-%d %H:%M}",
        f"- Что проверяли: `{target}`",
        f"- Профиль: `{profile}`, модель: `{model}`",
        f"- Частей кода: {n_chunks}",
        f"- Токены: input {usage['input']}, output {usage['output']}",
    ]
    if any(usage[k] for k in BREAKDOWN):
        out.append("- Разбивка input (по данным сервера):")
        out.extend(f"  - {label}: {usage[k]}" for k, label in BREAKDOWN.items())
    out.append("")
    if errors:
        out.append("## Проверка прервана")
        out.extend(f"- {e}" for e in errors)
        out.append("")
    out += ["## Найденные проблемы", ""]
    if rows:
        out += ["| Важность | Файл | Строка | Проблема | Исправление |",
                "|---|---|---|---|---|"]
        for r in sorted(rows, key=lambda r: _rank(r[0])):
            out.append("| " + " | ".join(_cell(c) for c in r) + " |")
    else:
        out.append("Проблем в таблице нет.")
    out.append("")
    for part, raw in raw_blocks:
        out += [f"## Ответ модели в другом формате (часть {part})", "",
                "Модель ответила не по шаблону, вот её текст без изменений:", "",
                "~~~text", raw, "~~~", ""]
    return "\n".join(out)


def run_review(provider, profile_name, target, settings, out_dir):
    files, skipped = collect_files(target)
    if not files:
        raise ToolkitError("В этом пути нет текстовых файлов с кодом для проверки.")

    chunks = build_chunks(files, settings["chunk_tokens"])
    est_in = sum(est_tokens(c) + est_tokens(SYSTEM) + 20 for c in chunks)
    print(f"Файлов к проверке: {len(files)} (пропущено: {skipped})")
    print(f"Частей: {len(chunks)}")
    print(f"Примерно токенов на входе: ~{est_in} (это грубая оценка)")
    print(f"Ответ - до {settings['max_output_tokens']} токенов на каждую часть.")
    if input("Отправить в нейросеть? (y/n): ").strip().lower() not in ("y", "yes", "д", "да"):
        print("Отменено, ничего не отправлено.")
        return

    rows, raw_blocks, errors = [], [], []
    usage = {"input": 0, "output": 0, **{k: 0 for k in BREAKDOWN}}
    for i, chunk in enumerate(chunks, 1):
        print(f"Часть {i} из {len(chunks)}...")
        msg = [{"role": "user", "content": f"Часть {i} из {len(chunks)}. Проверь код:\n\n{chunk}"}]
        try:
            text, u = provider.send(SYSTEM, msg)
        except ToolkitError as exc:
            errors.append(f"Часть {i}: {exc}")
            print(f"Ошибка: {exc}")
            break
        for k in usage:
            usage[k] += u.get(k, 0) or 0
        found = parse_response(text)
        rows.extend(found)
        no_issues = re.search(r"ПРОБЛЕМ\s+НЕТ", text, re.I)
        if not found and not no_issues and text.strip():
            raw_blocks.append((i, text.strip()))

    out_dir.mkdir(exist_ok=True)
    path = Path(out_dir) / "review_report.md"
    report = build_report(profile_name, provider.model, target, rows, raw_blocks,
                          errors, usage, len(chunks))
    path.write_text(report, encoding="utf-8")
    print(f"\nОтчёт сохранён: {path}")
    print(f"Потрачено токенов: input {usage['input']}, output {usage['output']}")
    if any(usage[k] for k in BREAKDOWN):
        print("Разбивка input (по данным сервера):")
        for k, label in BREAKDOWN.items():
            print(f"  {label}: {usage[k]}")
    if errors:
        raise ToolkitError("Проверка прервана раньше времени, в отчёте только то, что успело проверить.")
