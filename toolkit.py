"""ai-toolkit: консольный инструмент, работающий с любой нейросетью.

Пример: python toolkit.py --profile deepseek review ./мой_проект
"""

import argparse
import os
import sys
from pathlib import Path

from providers import TYPES, ToolkitError, create_provider

BASE_DIR = Path(__file__).resolve().parent
DEFAULTS = {"chunk_tokens": 30000, "max_output_tokens": 4096, "timeout_seconds": 120}


def load_config(path):
    try:
        import yaml
        from dotenv import load_dotenv
    except ImportError:
        raise ToolkitError("Не хватает библиотек. Выполни: pip install -r requirements.txt")
    load_dotenv(BASE_DIR / ".env")

    if not path.exists():
        raise ToolkitError(
            f"Не найден файл {path.name}. Скопируй config.example.yaml в config.yaml."
        )
    try:
        cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ToolkitError(f"Ошибка в {path.name} (проверь отступы и двоеточия): {exc}")
    if not isinstance(cfg.get("profiles"), dict) or not cfg["profiles"]:
        raise ToolkitError(f"В {path.name} нет раздела profiles.")
    return cfg


def get_profile(cfg, name):
    profiles = cfg["profiles"]
    if name not in profiles:
        raise ToolkitError(
            f"Профиль '{name}' не найден в config.yaml. Есть: {', '.join(profiles)}."
        )
    profile = profiles[name]
    for field in ("type", "base_url", "key_env", "model"):
        if not profile.get(field):
            raise ToolkitError(f"В профиле '{name}' не заполнено поле {field}.")
    if profile["type"] not in TYPES:
        raise ToolkitError(
            f"В профиле '{name}' type='{profile['type']}'. Допустимо: {', '.join(TYPES)}."
        )
    url = str(profile["base_url"]).strip()
    if not url.startswith(("http://", "https://")) or " " in url:
        raise ToolkitError(
            f"В профиле '{name}' неверный base_url: «{url}». Адрес должен начинаться "
            "с http:// или https://, например https://api.deepseek.com"
        )
    profile["base_url"] = url
    return profile


def get_key(profile):
    env_name = str(profile["key_env"])
    if env_name.upper() == "NONE":
        return None
    key = os.environ.get(env_name, "").strip()
    if not key:
        raise ToolkitError(
            f"Не найден ключ {env_name}. Впиши его в файл .env "
            f"(образец в .env.example), строкой {env_name}=твой_ключ"
        )
    return key


def positive_int(settings, name):
    try:
        value = int(settings[name])
        if value <= 0:
            raise ValueError
        return value
    except (TypeError, ValueError):
        raise ToolkitError(f"В config.yaml параметр {name} должен быть целым числом больше 0.")


def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass

    # Если ввод пришёл не с клавиатуры (конвейер), PowerShell добавляет в начало
    # невидимый BOM. utf-8-sig его убирает.
    if not sys.stdin.isatty():
        try:
            sys.stdin.reconfigure(encoding="utf-8-sig")
        except Exception:
            pass

    parser = argparse.ArgumentParser(description="ai-toolkit: работа с любой нейросетью")
    parser.add_argument("--profile", default=None, help="имя профиля из config.yaml")
    parser.add_argument("--config", default=str(BASE_DIR / "config.yaml"), help="путь к конфигу")
    sub = parser.add_subparsers(dest="command", required=True)
    rev = sub.add_parser("review", help="проверить код файла или папки")
    rev.add_argument("path", help="файл или папка")
    args = parser.parse_args()

    try:
        cfg = load_config(Path(args.config))
        name = args.profile or cfg.get("default_profile") or next(iter(cfg["profiles"]))
        profile = get_profile(cfg, name)

        settings = dict(DEFAULTS)
        settings.update(cfg.get("settings") or {})
        if "max_output_tokens" in profile:  # профиль может переопределить
            settings["max_output_tokens"] = profile["max_output_tokens"]
        for key in DEFAULTS:
            settings[key] = positive_int(settings, key)

        provider = create_provider(
            profile, get_key(profile), settings["max_output_tokens"],
            settings["timeout_seconds"],
        )
        if args.command == "review":
            from review import run_review
            print(f"Профиль: {name}, модель: {profile['model']}")
            run_review(provider, name, args.path, settings, BASE_DIR / "output")
    except ToolkitError as exc:
        print(f"\nОшибка: {exc}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nОстановлено пользователем.")
        sys.exit(130)


if __name__ == "__main__":
    main()
