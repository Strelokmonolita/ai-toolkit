"""Результат проверки и его оформление в виде отчёта."""

import json
import re
from dataclasses import dataclass, field
from datetime import datetime

# Доп. поля usage есть только у провайдера anthropic.
BREAKDOWN = {
    "input_tokens": "input_tokens (обычные)",
    "cache_creation_input_tokens": "cache_creation_input_tokens (запись в кэш)",
    "cache_read_input_tokens": "cache_read_input_tokens (чтение из кэша)",
}
# Внутри и в JSON важность хранится кодом, в Markdown показывается по-русски.
SEVERITY_LABELS = {"high": "Высокая", "medium": "Средняя", "low": "Низкая"}
RANK = {"high": 0, "medium": 1, "low": 2}
_RU_STEMS = {"выс": "high", "сред": "medium", "низ": "low"}
_EN_WORDS = {"high": "high", "medium": "medium", "med": "medium", "low": "low"}


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


def normalize_severity(sev):
    """Код важности: high, medium или low. None, если уровень не распознан.

    Понимает русские слова в любом регистре («Высокая», «СРЕДНЯЯ»), английские
    («High», «medium», «med») и коды.
    """
    s = sev.strip().lower()
    if s in _EN_WORDS:
        return _EN_WORDS[s]
    for stem, code in _RU_STEMS.items():
        if s.startswith(stem):
            return code
    return None


def severity_code(sev):
    """Код важности, а если уровень не распознан, исходная строка."""
    return normalize_severity(sev) or sev


def severity_rank(sev):
    """0 - high, 1 - medium, 2 - low, 3 - не распознана."""
    return RANK.get(normalize_severity(sev), 3)


def has_findings_at_or_above(rows, level):
    """Есть ли находки уровня level (код high, medium или low) или выше."""
    limit = RANK[level]
    return any(severity_rank(r[0]) <= limit for r in rows)


def line_number(text):
    """Номер строки как int. Диапазоны («12-15») и мусор дают None."""
    s = str(text).strip()
    return int(s) if re.fullmatch(r"\d+", s) else None


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
        for sev, *rest in sorted(result.rows, key=lambda r: severity_rank(r[0])):
            label = SEVERITY_LABELS.get(severity_code(sev), sev)
            out.append("| " + " | ".join(_cell(c) for c in (label, *rest)) + " |")
    else:
        out.append("Проблем в таблице нет.")
    out.append("")
    for part, raw in result.raw_blocks:
        out += [f"## Ответ модели в другом формате (часть {part})", "",
                "Модель ответила не по шаблону, вот её текст без изменений:", "",
                "~~~text", raw, "~~~", ""]
    return "\n".join(out)


def _issue(row):
    sev, file_, line, problem, fix = row
    return {"severity": severity_code(sev), "file": file_, "line": line_number(line),
            "problem": problem, "fix": fix}


def build_json(result):
    """JSON-отчёт по ReviewResult (те же данные, что в markdown)."""
    data = {
        "date": f"{datetime.now():%Y-%m-%d %H:%M}",
        "target": result.target,
        "profile": result.profile,
        "model": result.model,
        "chunks": result.n_chunks,
        "usage": result.usage,
        "errors": result.errors,
        "warnings": result.warnings,
        "issues": [_issue(r) for r in sorted(result.rows, key=lambda r: severity_rank(r[0]))],
        "raw_blocks": [{"chunk": part, "text": raw} for part, raw in result.raw_blocks],
    }
    return json.dumps(data, ensure_ascii=False, indent=2)
