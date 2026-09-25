import os
import unittest
from unittest import mock

from llm import client

PRICE = {"input": 0.3, "output": 1.2, "input_cached": 0.03}
NO_PRICES = {"LLM_PRICE_INPUT": "", "LLM_PRICE_OUTPUT": "", "LLM_PRICE_INPUT_CACHED": ""}


class PriceTest(unittest.TestCase):
    def test_tokens_deepseek_and_openai_cache_fields(self):
        deepseek = {"prompt_tokens": 1000, "completion_tokens": 50, "prompt_cache_hit_tokens": 800}
        openai = {"prompt_tokens": 1000, "completion_tokens": 50, "prompt_tokens_details": {"cached_tokens": 800}}
        self.assertEqual(client.tokens(deepseek), (1000, 800, 50))
        self.assertEqual(client.tokens(openai), (1000, 800, 50))
        self.assertEqual(client.tokens({}), (0, 0, 0))

    def test_cost_by_tokens(self):
        usage = {"prompt_tokens": 1_000_000, "completion_tokens": 1_000_000, "prompt_cache_hit_tokens": 500_000}
        self.assertAlmostEqual(client.cost(usage, PRICE), 0.5 * 0.3 + 0.5 * 0.03 + 1.2)

    def test_provider_cost_wins(self):
        self.assertEqual(client.cost({"cost": 0.0042, "prompt_tokens": 10}, PRICE), 0.0042)
        self.assertEqual(client.cost({"cost": 0.0042}, None), 0.0042)

    def test_unknown_price_is_none_not_zero(self):
        self.assertIsNone(client.cost({"prompt_tokens": 10, "completion_tokens": 5}, None))
        self.assertIsNone(client.estimate("prompt", 1000, 10, None))

    def test_prices_from_env(self):
        with mock.patch.dict(os.environ, NO_PRICES):
            self.assertIsNone(client.prices())
        with mock.patch.dict(os.environ, {**NO_PRICES, "LLM_PRICE_INPUT": "0.3", "LLM_PRICE_OUTPUT": "1.2"}):
            self.assertEqual(client.prices(), {"input": 0.3, "output": 1.2, "input_cached": 0.3})
        with mock.patch.dict(os.environ, {"LLM_PRICE_INPUT": "0.3", "LLM_PRICE_OUTPUT": "1.2",
                                          "LLM_PRICE_INPUT_CACHED": "0.03"}):
            self.assertEqual(client.prices(), PRICE)

    def test_estimate_counts_cache_after_first_batch(self):
        prompt = "x" * 3500   # 1000 токенов при 3.5 символа на токен
        full = dict(PRICE, input_cached=PRICE["input"])
        # 20 отзывов - две пачки: со скидкой на кэш второй промпт дешевле
        self.assertLess(client.estimate(prompt, 0, 20, PRICE), client.estimate(prompt, 0, 20, full))
        self.assertEqual(client.estimate(prompt, 0, 0, PRICE), 0.0)


if __name__ == "__main__":
    unittest.main()
