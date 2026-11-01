# ai-toolkit

Консольный инструмент, который работает с любой нейросетью. Команда `review`
читает код из файла или папки, отправляет его выбранной модели и сохраняет отчёт
`output/review_report.md`: таблица «важность / файл / строка / проблема / исправление».

Модель выбирается профилем в `config.yaml`, код программы при этом не меняется.

## Как это устроено

- `config.yaml`: список профилей (тип API, адрес, модель). Личный файл, в git не попадает.
- `.env`: ключи. Только здесь, не в коде и не в конфиге. В git не попадает.
- `providers/`: два «переходника».
  - `anthropic`: Claude и прокси с Anthropic API.
  - `openai`: всё, что говорит на языке OpenAI: OpenAI, DeepSeek, OpenRouter,
    Ollama, LM Studio.

## Что нужно

- Python 3.13. На Python 3.15 rc установка падает на `pyyaml` (нет готовой сборки).
- Ключ от нейросети. Для локальной модели (Ollama, LM Studio) ключ не нужен.

## Установка

Windows (PowerShell):

```powershell
py -3.13 -m venv venv
venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
copy config.example.yaml config.yaml
```

Linux / macOS:

```bash
python3.13 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
cp config.example.yaml config.yaml
```

Дальше:
1. Открой `.env` и впиши ключ: `CLAUDE_KEY=твой_ключ` (без кавычек и пробелов).
2. В `config.yaml` поправь `base_url` и `model` под свою нейросеть. Структура та же,
   что в `config.example.yaml`: блоки `settings` и `profiles`.

> **Ключи не коммитить.** `.env` и `config.yaml` указаны в `.gitignore`. Не добавляй их
> в git принудительно (`git add -f`), не вписывай ключ в `config.yaml` и не отправляй
> эти файлы в чат или в issue.

## Примеры профилей в config.yaml

```yaml
profiles:
  # Claude (Anthropic). base_url БЕЗ /v1. Свой прокси: впиши его адрес.
  claude:
    type: anthropic
    base_url: https://api.anthropic.com
    key_env: CLAUDE_KEY          # имя переменной в .env
    model: claude-sonnet-5-5

  # OpenAI-совместимый сервис (здесь DeepSeek). base_url обычно с /v1,
  # если у сервиса так в документации.
  deepseek:
    type: openai
    base_url: https://api.deepseek.com
    key_env: DEEPSEEK_KEY
    model: deepseek-chat

  # Ollama на своём компьютере. Ключ не нужен: key_env: NONE.
  # Сначала скачай модель: ollama pull llama3
  local:
    type: openai
    base_url: http://localhost:11434/v1
    key_env: NONE
    model: llama3
```

Для LM Studio адрес обычно `http://localhost:1234/v1`. Названия моделей бери из
документации сервиса, они меняются. Готовые профили `claude`, `deepseek`, `openrouter`
и `local` есть в `config.example.yaml`.

## Запуск

Проверка файла. Перед отправкой программа покажет оценку токенов и спросит `y/n`:

```bash
python toolkit.py review test_sample/bug.py
```

Проверка папки без вопросов, отчёт в свой файл:

```bash
python toolkit.py -y review ./мой_проект --output output/my_review.md
```

Отчёт в JSON вместо markdown (файл `review_report.json`):

```bash
python toolkit.py review ./мой_проект --format json
```

Другой профиль из config.yaml:

```bash
python toolkit.py --profile deepseek review ./мой_проект
python toolkit.py --profile local review ./main.py
```

Исключить пути по glob-шаблону (относительно проверяемой папки, можно несколько раз):

```bash
python toolkit.py review ./мой_проект --exclude "tests/*" --exclude "*.min.js"
```

Проверить только файлы, изменённые относительно ветки `main` (нужен git; без `--base`
берётся `HEAD`):

```bash
python toolkit.py review . --changed --base main
```

Завершиться с кодом 2, если есть находки уровня `high` или выше:

```bash
python toolkit.py review . --fail-on high
```

Файл `test_sample/bug.py` содержит ошибки, сделанные специально: на нём удобно
проверить, что всё работает.

### Коды возврата

| Код | Значение |
|---|---|
| 0 | проверка завершена, отчёт сохранён (сами находки код не меняют) |
| 1 | ошибка: неверные аргументы, конфиг, ключ, сеть, запись отчёта |
| 2 | сработал `--fail-on`: есть находки этого уровня или выше |
| 130 | остановлено пользователем (Ctrl+C) |

Перед отправкой программа покажет примерное число токенов и спросит `y/n`.
В конце напишет, сколько токенов потрачено (input/output). Для Claude показывается
разбивка input по полям usage сервера.

## Настройки (раздел `settings` в config.yaml)

| Параметр | Что делает | По умолчанию |
|---|---|---|
| `chunk_tokens` | размер одной части кода | 30000 |
| `max_output_tokens` | предел длины ответа на каждую часть | 4096 |
| `timeout_seconds` | сколько ждать ответ | 120 |

Если ответ в отчёте обрезан, увеличь `max_output_tokens`. В профиле с
`type: anthropic` можно задать `anthropic_version` (по умолчанию `2023-06-01`):
некоторые прокси не принимают более новые значения.

## Что пропускается при проверке

Папки `.git`, `node_modules`, `venv`, `__pycache__`, `output` и др.; бинарные файлы;
файлы больше 500 КБ; `.env*` и `config.yaml` (чтобы ключи не ушли в нейросеть).

## Важно знать

- Число токенов до отправки это грубая оценка (около 1 токена на 3 символа).
- Код уходит на сервер выбранной нейросети. Для закрытого кода используй локальную модель.
- Нейросеть может ошибаться, находки нужно проверять самому.
- Если модель ответила не по шаблону, её текст попадает в отчёт отдельным блоком.

## Проверка в GitHub Actions

В репозитории нет `.env` и `config.yaml`, поэтому шаг создаёт конфиг из образца.
Ключ передаётся переменной окружения из секретов: программа читает её напрямую,
файл `.env` в CI не нужен. Файл `.github/workflows/review.yml`:

```yaml
name: code-review
on: pull_request
jobs:
  review:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0          # нужна история, чтобы работал --base
      - uses: actions/setup-python@v5
        with:
          python-version: "3.13"
      - run: pip install -r requirements.txt
      - run: cp config.example.yaml config.yaml
      - run: python toolkit.py -y review . --changed --base origin/${{ github.base_ref }} --fail-on high
        env:
          CLAUDE_KEY: ${{ secrets.CLAUDE_KEY }}
```

Отчёт остаётся на раннере в `output/review_report.md`. Чтобы сохранить его, добавь шаг
`actions/upload-artifact`. Шаг упадёт с кодом 2, если найдены проблемы `high`.

## Частые ошибки

| Сообщение | Что делать |
|---|---|
| Не найден ключ | впиши его в `.env` (имя как в `key_env`) |
| Неверный ключ (401) | проверь ключ в `.env` |
| Не найдено (404) | проверь `base_url` и `model` в `config.yaml` |
| Неверный base_url | адрес должен начинаться с `http://` или `https://` |
| Не удалось подключиться | проверь интернет, адрес, запущен ли Ollama/LM Studio |
| Таймаут | повтори или увеличь `timeout_seconds` |

## Лицензия

MIT, см. файл `LICENSE`.
