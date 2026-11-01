"""Провайдер для OpenAI-совместимых API: OpenAI, DeepSeek, OpenRouter, Ollama, LM Studio."""

from .base import Provider, Reply, ToolkitError, translate_error


class OpenAIProvider(Provider):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        try:
            import openai
        except ImportError:
            raise ToolkitError(
                "Не установлена библиотека openai. Выполни: pip install -r requirements.txt"
            )
        self._sdk = openai
        self._client = openai.OpenAI(
            base_url=self.base_url,
            # Локальным моделям ключ не нужен, но библиотека требует непустую строку.
            api_key=self.api_key or "not-needed",
            timeout=self.timeout,
        )

    def send(self, system, messages):
        full = [{"role": "system", "content": system}] + list(messages)
        try:
            resp = self._client.chat.completions.create(
                model=self.model,
                max_tokens=self.max_output_tokens,
                messages=full,
            )
        except self._sdk.APIError as exc:
            raise translate_error(exc, self._sdk, self.base_url, self.model)

        if not resp.choices:
            raise ToolkitError("Нейросеть вернула пустой ответ.")
        choice = resp.choices[0]
        text = choice.message.content or ""
        u = resp.usage
        # Некоторые локальные серверы не присылают usage - тогда будет 0.
        usage = {
            "input": getattr(u, "prompt_tokens", 0) or 0,
            "output": getattr(u, "completion_tokens", 0) or 0,
        }
        return Reply(text, usage, truncated=choice.finish_reason == "length")
