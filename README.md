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
2. В `config.yaml` поправь `base_url` и `model` под свою нейросеть.

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
  ollama:
    type: openai
    base_url: http://localhost:11434/v1
    key_env: NONE
    model: llama3
```

Для LM Studio адрес обычно `http://localhost:1234/v1`. Названия моделей бери из
документации сервиса, они меняются.

## Запуск

```bash
python toolkit.py review test_sample/bug.py
python toolkit.py --profile deepseek review ./мой_проект
python toolkit.py --profile ollama review ./main.py
```

Файл `test_sample/bug.py` содержит ошибки, сделанные специально: на нём удобно
проверить, что всё работает.

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
