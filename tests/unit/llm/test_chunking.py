import unittest

from meeting_agent.llm.chunking import BudgetPolicy, estimate_text_tokens


class ChunkingTests(unittest.TestCase):
    def test_token_estimate_is_deterministic(self):
        policy = BudgetPolicy(ctx=100, output_tokens=10, safety_tokens=0, chars_per_token=2.0, fixed_overhead_tokens=3)
        self.assertEqual(estimate_text_tokens("abcd", policy), 5)


if __name__ == "__main__":
    unittest.main()
