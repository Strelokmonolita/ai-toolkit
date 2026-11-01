import unittest
from types import SimpleNamespace as NS

from providers import TYPES, ToolkitError, create_provider


def make(ptype, key="k"):
    return create_provider(
        {"type": ptype, "base_url": "https://x.test", "model": "m"}, key, 100, 5)


class AnthropicProviderTest(unittest.TestCase):
    def reply(self, stop_reason):
        provider = make("anthropic")
        provider._client = NS(messages=NS(create=lambda **kw: NS(
            content=[NS(type="text", text="hi"), NS(type="thinking", text="skip")],
            stop_reason=stop_reason,
            usage=NS(input_tokens=3, output_tokens=4,
                     cache_creation_input_tokens=2, cache_read_input_tokens=1))))
        return provider.send("system", [])

    def test_text_and_usage(self):
        r = self.reply("end_turn")
        self.assertEqual(r.text, "hi")
        self.assertEqual(r.usage["input"], 6)  # 3 + 2 + 1
        self.assertEqual(r.usage["output"], 4)
        self.assertFalse(r.truncated)

    def test_truncated_on_max_tokens(self):
        self.assertTrue(self.reply("max_tokens").truncated)


class OpenAIProviderTest(unittest.TestCase):
    def reply(self, finish_reason, usage=None, choices=True):
        provider = make("openai", key=None)
        result = NS(choices=[NS(message=NS(content="yo"), finish_reason=finish_reason)]
                    if choices else [], usage=usage)
        provider._client = NS(chat=NS(completions=NS(create=lambda **kw: result)))
        return provider.send("system", [])

    def test_text_and_usage(self):
        r = self.reply("stop", NS(prompt_tokens=7, completion_tokens=2))
        self.assertEqual((r.text, r.usage), ("yo", {"input": 7, "output": 2}))
        self.assertFalse(r.truncated)

    def test_server_without_usage(self):
        self.assertEqual(self.reply("stop").usage, {"input": 0, "output": 0})

    def test_truncated_on_length(self):
        self.assertTrue(self.reply("length").truncated)

    def test_empty_choices(self):
        with self.assertRaises(ToolkitError):
            self.reply("stop", choices=False)


class FactoryTest(unittest.TestCase):
    def test_unknown_type(self):
        with self.assertRaises(ToolkitError):
            create_provider({"type": "gemini", "base_url": "https://x.test", "model": "m"},
                            "k", 100, 5)

    def test_known_types(self):
        self.assertEqual(set(TYPES), {"anthropic", "openai"})


if __name__ == "__main__":
    unittest.main()
