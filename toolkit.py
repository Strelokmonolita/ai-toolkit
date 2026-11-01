"""ai-toolkit: консольный инструмент, работающий с любой нейросетью.

Пример: python toolkit.py --profile deepseek review ./мой_проект
"""

import argparse
import os
import sys
from pathlib import Path

from providers import TYPES, ToolkitError, create_provider

BASE_DIR = Path(__file__).resolve().parent
VERSION = "0.2.0"
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
    if not isinstance(profile, dict):
        raise ToolkitError(f"Профиль '{name}' в config.yaml должен содержать поля type, base_url и т.д.")
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


class _Parser(argparse.ArgumentParser):
    """При ошибке аргументов выходит с кодом 1: код 2 оставлен за --fail-on."""

    def error(self, message):
        self.print_usage(sys.stderr)
        self.exit(1, f"{self.prog}: ошибка: {message}\n")


def build_parser():
    # Общие флаги нужны и до, и после подкоманды. У подкоманд default=SUPPRESS,
    # чтобы не затирать значение, заданное до подкоманды.
    def common(suppress):
        p = argparse.ArgumentParser(add_help=False)
        p.add_argument("--profile", default=argparse.SUPPRESS if suppress else None,
                       help="имя профиля из config.yaml")
        p.add_argument("--config", default=argparse.SUPPRESS if suppress else str(BASE_DIR / "config.yaml"),
                       help="путь к конфигу")
        return p

    parser = _Parser(description="ai-toolkit: работа с любой нейросетью",
                                     parents=[common(False)])
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    sub = parser.add_subparsers(dest="command", required=True)
    rev = sub.add_parser("review", help="проверить код файла или папки",
                         parents=[common(True)])
    rev.add_argument("path", help="файл или папка")
    rev.add_argument("-y", "--yes", action="store_true",
                     help="не задавать вопросов, сразу отправлять в нейросеть")
    rev.add_argument("--output", metavar="PATH",
                     help="файл отчёта (или папка, если путь существует как папка)")
    rev.add_argument("--format", choices=("md", "json"), default="md", help="формат отчёта")
    rev.add_argument("--fail-on", choices=("high", "medium", "low"), default=None,
                     help="код возврата 2, если есть находки этого уровня или выше")
    rev.add_argument("--exclude", metavar="PATTERN", action="append",
                     help="не проверять пути по glob-шаблону (относительно папки); можно несколько раз")
    rev.add_argument("--changed", nargs="?", const="HEAD", default=None, metavar="REF",
                     help="проверить только файлы, изменённые относительно REF (по умолчанию HEAD). "
                          "Путь пиши раньше этого флага, иначе он станет REF")
    sub.add_parser("profiles", help="показать профили из конфига",
                   parents=[common(True)])
    return parser


def list_profiles(cfg):
    default = cfg.get("default_profile") or next(iter(cfg["profiles"]))
    for name, profile in cfg["profiles"].items():
        profile = profile if isinstance(profile, dict) else {}
        mark = " (по умолчанию)" if name == default else ""
        print(f"{name}{mark}: type={profile.get('type', '?')}, model={profile.get('model', '?')}")


def main(argv=None):
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

    args = build_parser().parse_args(argv)

    try:
        cfg = load_config(Path(args.config))
        if args.command == "profiles":
            list_profiles(cfg)
            return
        name = args.profile or cfg.get("default_profile") or next(iter(cfg["profiles"]))
        profile = get_profile(cfg, name)

        user_settings = cfg.get("settings") or {}
        if not isinstance(user_settings, dict):
            raise ToolkitError("Раздел settings в config.yaml должен быть списком «параметр: значение».")
        settings = dict(DEFAULTS)
        settings.update(user_settings)
        if "max_output_tokens" in profile:  # профиль может переопределить
            settings["max_output_tokens"] = profile["max_output_tokens"]
        for key in DEFAULTS:
            settings[key] = positive_int(settings, key)

        provider = create_provider(
            profile, get_key(profile), settings["max_output_tokens"],
            settings["timeout_seconds"],
        )
        if args.command == "review":
            from report import has_findings_at_or_above
            from review import run_review
            print(f"Профиль: {name}, модель: {profile['model']}")
            result = run_review(provider, name, args.path, settings, BASE_DIR / "output",
                                assume_yes=args.yes, fmt=args.format, output=args.output,
                                excludes=args.exclude or [], changed=args.changed)
            if args.fail_on and result is not None and has_findings_at_or_above(result.rows, args.fail_on):
                print(f"Есть проблемы уровня {args.fail_on} и выше, код возврата 2.", file=sys.stderr)
                sys.exit(2)
    except ToolkitError as exc:
        print(f"\nОшибка: {exc}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nОстановлено пользователем.")
        sys.exit(130)


if __name__ == "__main__":
    main()
