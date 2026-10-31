"""Базовый класс провайдера и общие ошибки."""


class ToolkitError(Exception):
    """Ошибка с понятным текстом на русском. Её показываем пользователю как есть."""


class Provider:
    """Один «переходник» к нейросети. Наследники реализуют send()."""

    def __init__(self, base_url, api_key, model, max_output_tokens, timeout, options=None):
        self.options = options or {}  # весь профиль из config.yaml (доп. поля)
        self.base_url = base_url
        self.api_key = api_key
        self.model = model
        self.max_output_tokens = max_output_tokens
        self.timeout = timeout

    def send(self, system, messages):
        """Отправить запрос. Вернуть (text, usage).

        usage = {"input": число токенов на входе, "output": число токенов на выходе}
        """
        raise NotImplementedError


def translate_error(exc, sdk, base_url, model):
    """Превращает ошибку библиотеки (anthropic/openai) в понятный текст.

    sdk - сама библиотека (модуль anthropic или openai): у обеих
    одинаковые названия классов ошибок.
    """
    if isinstance(exc, sdk.APITimeoutError):
        return ToolkitError(
            "Нейросеть не ответила вовремя (таймаут). Попробуй ещё раз, "
            "увеличь timeout_seconds в config.yaml или уменьши chunk_tokens."
        )
    if isinstance(exc, sdk.APIConnectionError):
        return ToolkitError(
            f"Не удалось подключиться к {base_url}. Проверь интернет, "
            "адрес base_url в config.yaml и (для локальной модели) что программа запущена."
        )
    if isinstance(exc, sdk.AuthenticationError):
        return ToolkitError(
            "Неверный ключ (ошибка 401). Проверь ключ в файле .env: "
            "нет ли лишних пробелов, кавычек и не истёк ли он."
        )
    if isinstance(exc, sdk.PermissionDeniedError):
        return ToolkitError(
            "Доступ запрещён (ошибка 403). У ключа нет прав на эту модель или регион."
        )
    if isinstance(exc, sdk.NotFoundError):
        return ToolkitError(
            f"Не найдено (ошибка 404). Проверь base_url ({base_url}) и название "
            f"модели ({model}) в config.yaml. Частая причина: для type: anthropic "
            "адрес пишется без /v1, а для type: openai обычно нужен /v1 на конце."
        )
    if isinstance(exc, sdk.RateLimitError):
        return ToolkitError(
            "Слишком много запросов или закончились деньги на счёте (ошибка 429). "
            "Подожди немного или проверь баланс."
        )
    if isinstance(exc, sdk.BadRequestError):
        return ToolkitError(
            f"Сервер не принял запрос (ошибка 400). Возможно, слишком большая часть "
            f"кода или неподходящие параметры. Подробности: {exc}"
        )
    if isinstance(exc, sdk.APIStatusError):
        return ToolkitError(
            f"Сервер вернул ошибку {exc.status_code}. Подробности: {exc}"
        )
    return ToolkitError(f"Неожиданная ошибка при обращении к нейросети: {exc}")
