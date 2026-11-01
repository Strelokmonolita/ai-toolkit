"""Выбор провайдера по полю type из config.yaml."""

from .base import Provider, Reply, ToolkitError

TYPES = ("anthropic", "openai")


def create_provider(profile, api_key, max_output_tokens, timeout):
    """Создаёт нужный провайдер по профилю из конфига."""
    ptype = profile.get("type")
    args = (profile["base_url"], api_key, profile["model"], max_output_tokens, timeout, profile)

    # Импортируем только нужный, чтобы не требовать обе библиотеки сразу.
    if ptype == "anthropic":
        from .anthropic_provider import AnthropicProvider
        return AnthropicProvider(*args)
    if ptype == "openai":
        from .openai_provider import OpenAIProvider
        return OpenAIProvider(*args)
    raise ToolkitError(
        f"Неизвестный type '{ptype}' в профиле. Допустимо: {', '.join(TYPES)}."
    )


__all__ = ["Provider", "Reply", "ToolkitError", "create_provider", "TYPES"]
