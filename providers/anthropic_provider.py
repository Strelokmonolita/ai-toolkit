"""Провайдер для Claude (и прокси, совместимых с Anthropic API)."""

from .base import Provider, ToolkitError, translate_error


class AnthropicProvider(Provider):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        try:
            import anthropic
        except ImportError:
            raise ToolkitError(
                "Не установлена библиотека anthropic. Выполни: pip install -r requirements.txt"
            )
        self._sdk = anthropic
        # auth_token = заголовок Authorization: Bearer ...
        self._client = anthropic.Anthropic(
            base_url=self.base_url,
            auth_token=self.api_key,
            timeout=self.timeout,
            # Прокси и старые серверы не знают новых дат версии, которые шлёт
            # библиотека сама, поэтому фиксируем версию API. Можно поменять
            # в профиле: anthropic_version: "2023-06-01"
            default_headers={
                "anthropic-version": str(self.options.get("anthropic_version", "2023-06-01"))
            },
        )

    def send(self, system, messages):
        try:
            # Параметр thinking намеренно не передаём.
            resp = self._client.messages.create(
                model=self.model,
                max_tokens=self.max_output_tokens,
                system=system,
                messages=messages,
            )
        except self._sdk.APIError as exc:
            raise translate_error(exc, self._sdk, self.base_url, self.model)

        text = "".join(
            block.text for block in resp.content if getattr(block, "type", "") == "text"
        )
        u = resp.usage
        plain = getattr(u, "input_tokens", 0) or 0
        cache_write = getattr(u, "cache_creation_input_tokens", 0) or 0
        cache_read = getattr(u, "cache_read_input_tokens", 0) or 0
        usage = {
            # Итоговый вход = сумма трёх input-полей.
            "input": plain + cache_write + cache_read,
            "output": getattr(u, "output_tokens", 0) or 0,
            # Разбивка для отчёта.
            "input_tokens": plain,
            "cache_creation_input_tokens": cache_write,
            "cache_read_input_tokens": cache_read,
        }
        return text, usage
