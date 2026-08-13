from types import SimpleNamespace
import unittest
from unittest.mock import patch

from open_webui.retrieval.utils import agenerate_gemini_batch_embeddings


class GeminiEmbeddingBatchTests(unittest.IsolatedAsyncioTestCase):
    async def test_gemini_embedding_2_wraps_each_text_as_independent_content(self):
        """Embedding 2 must not aggregate a plain list of strings into one vector."""
        from google import genai
        from google.genai import types

        captured = {}

        class FakeModels:
            def embed_content(self, *, model, contents, config):
                captured["model"] = model
                captured["contents"] = contents
                captured["config"] = config

                # Gemini Embedding 2 aggregates a plain list of parts/strings into
                # one embedding. Separate Content objects produce separate vectors.
                count = 1 if all(isinstance(item, str) for item in contents) else len(contents)
                return SimpleNamespace(
                    embeddings=[SimpleNamespace(values=[float(index)]) for index in range(count)]
                )

        class FakeClient:
            def __init__(self, *, api_key):
                self.assert_api_key(api_key)
                self.models = FakeModels()

            @staticmethod
            def assert_api_key(api_key):
                if api_key != "test-key":
                    raise AssertionError("unexpected API key")

        with patch.object(genai, "Client", FakeClient):
            result = await agenerate_gemini_batch_embeddings(
                "gemini-embedding-2",
                ["first chunk", "second chunk"],
                key="test-key",
                output_dimensionality=768,
            )

        self.assertEqual(result, [[0.0], [1.0]])
        self.assertEqual(captured["model"], "gemini-embedding-2")
        self.assertTrue(all(isinstance(item, types.Content) for item in captured["contents"]))
        self.assertEqual(
            [item.parts[0].text for item in captured["contents"]],
            ["first chunk", "second chunk"],
        )
        self.assertEqual(captured["config"].output_dimensionality, 768)


if __name__ == "__main__":
    unittest.main()
