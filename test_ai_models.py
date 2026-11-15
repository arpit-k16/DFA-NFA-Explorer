"""Tests for automatic provider and model selection (network mocked)."""
import unittest
from unittest.mock import patch

import ai_models


class ModelChoiceTests(unittest.TestCase):
    def test_openai_ranking(self):
        ids = ["gpt-4o-mini", "gpt-5.6-luna-mini", "gpt-5.6-sol", "gpt-4o-realtime-preview",
               "text-embedding-3-small", "gpt-5.6-sol-2026-08-05", "dall-e-3", "gpt-4.1"]
        ranked = ai_models.rank_openai(ids)
        self.assertEqual(ranked[0], "gpt-5.6-sol")
        self.assertNotIn("gpt-4o-realtime-preview", ranked)
        self.assertNotIn("text-embedding-3-small", ranked)
        self.assertLess(ranked.index("gpt-5.6-sol"), ranked.index("gpt-5.6-luna-mini"))

    def test_gemini_ranking(self):
        models = [{"name": "models/gemini-2.5-pro", "supportedGenerationMethods": ["generateContent"]},
                  {"name": "models/gemini-3.5-flash", "supportedGenerationMethods": ["generateContent"]},
                  {"name": "models/gemini-3.5-flash-lite", "supportedGenerationMethods": ["generateContent"]},
                  {"name": "models/gemini-embedding-001", "supportedGenerationMethods": ["embedContent"]},
                  {"name": "models/gemini-3.5-flash-image", "supportedGenerationMethods": ["generateContent"]}]
        self.assertEqual(ai_models.rank_gemini(models),
                         ["gemini-3.5-flash", "gemini-3.5-flash-lite", "gemini-2.5-pro"])

    def test_unavailable_model_tries_next_and_bad_key_tries_next_provider(self):
        calls = []

        def openai(text, key, model):
            calls.append(model)
            if model == "gpt-new":
                raise ValueError("OpenAI model 'gpt-new' is unavailable for this account.")
            raise ValueError("OpenAI rate limit or quota reached (HTTP 429).")

        def gemini(text, key, model):
            calls.append(model)
            return {"spec": True}
        available = [("OpenAI", "k1", ["gpt-new", "gpt-old", "gpt-older"], openai),
                     ("Gemini", "k2", ["gemini-x"], gemini)]
        spec, label = ai_models.auto_generate("q", available)
        self.assertEqual(calls, ["gpt-new", "gpt-old", "gemini-x"])
        self.assertEqual(label, "Gemini · gemini-x")

    def test_named_model_first_and_list_failure_falls_back(self):
        with patch.object(ai_models, "_get_json", side_effect=OSError("offline")):
            ai_models._cache.clear()
            available = ai_models.providers("sk-test", "", openai_model="my-model")
        self.assertEqual(available[0][2][0], "my-model")
        self.assertIn(ai_models.openai_generator.DEFAULT_MODEL, available[0][2])
        with self.assertRaisesRegex(ValueError, "No AI model could answer"):
            ai_models.auto_generate("q", [("OpenAI", "k", ["m"], lambda *a: (_ for _ in ()).throw(
                ValueError("OpenAI rejected the API key (HTTP 401).")))])


if __name__ == "__main__":
    unittest.main()
