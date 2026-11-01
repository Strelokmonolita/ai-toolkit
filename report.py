"""Результат проверки и его оформление в виде отчёта."""

import json
from dataclasses import dataclass, field
from datetime import datetime

# Доп. поля usage есть только у провайдера anthropic.
BREAKDOWN = {
    "input_tokens": "input_tokens (обычные)",
    "cache_creation_input_tokens": "cache_creation_input_tokens (запись в кэш)",
    "cache_read_input_tokens": "cache_read_input_tokens (чтение из кэша)",
}
RANK = {"выс": 0, "сред": 1, "низ": 2}


def new_usage():
    return {"input": 0, "output": 0, **{k: 0 for k in BREAKDOWN}}


@dataclass
class ReviewResult:
    profile: str
    model: str
    target: str
    n_chunks: int
    rows: list = field(default_factory=list)        # (важность, файл, строка, проблема, исправление)
    raw_blocks: list = field(default_factory=list)  # (номер части, текст не по шаблону)
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    usage: dict = field(default_factory=new_usage)

    @property
    def has_breakdown(self):
        return any(self.usage[k] for k in BREAKDOWN)


def severity_rank(sev):
    """0 - высокая, 1 - средняя, 2 - низкая, 3 - не распознана."""
    s = sev.lower()
    for key, val in RANK.items():
        if s.startswith(key):
            return val
    return 3


def _cell(s):
    return s.replace("|", "\\|").replace("\n", " ")


def build_report(result):
    """Markdown-отчёт по ReviewResult."""
    out = [
        "# Отчёт о проверке кода",
        "",
        f"- Дата: {datetime.now():%Y-%m-%d %H:%M}",
        f"- Что проверяли: `{result.target}`",
        f"- Профиль: `{result.profile}`, модель: `{result.model}`",
        f"- Частей кода: {result.n_chunks}",
        f"- Токены: input {result.usage['input']}, output {result.usage['output']}",
    ]
    if result.has_breakdown:
        out.append("- Разбивка input (по данным сервера):")
        out.extend(f"  - {label}: {result.usage[k]}" for k, label in BREAKDOWN.items())
    out.append("")
    if result.errors:
        out.append("## Проверка прервана")
        out.extend(f"- {e}" for e in result.errors)
        out.append("")
    if result.warnings:
        out.append("## Предупреждения")
        out.extend(f"- {w}" for w in result.warnings)
        out.append("")
    out += ["## Найденные проблемы", ""]
    if result.rows:
        out += ["| Важность | Файл | Строка | Проблема | Исправление |",
                "|---|---|---|---|---|"]
        for r in sorted(result.rows, key=lambda r: severity_rank(r[0])):
            out.append("| " + " | ".join(_cell(c) for c in r) + " |")
    else:
        out.append("Проблем в таблице нет.")
    out.append("")
    for part, raw in result.raw_blocks:
        out += [f"## Ответ модели в другом формате (часть {part})", "",
                "Модель ответила не по шаблону, вот её текст без изменений:", "",
                "~~~text", raw, "~~~", ""]
    return "\n".join(out)


def build_json(result):
    """JSON-отчёт по ReviewResult (те же данные, что в markdown)."""
    keys = ("severity", "file", "line", "problem", "fix")
    data = {
        "date": f"{datetime.now():%Y-%m-%d %H:%M}",
        "target": result.target,
        "profile": result.profile,
        "model": result.model,
        "chunks": result.n_chunks,
        "usage": result.usage,
        "errors": result.errors,
        "warnings": result.warnings,
        "issues": [dict(zip(keys, r)) for r in sorted(result.rows, key=lambda r: severity_rank(r[0]))],
        "raw_blocks": [{"chunk": part, "text": raw} for part, raw in result.raw_blocks],
    }
    return json.dumps(data, ensure_ascii=False, indent=2)
