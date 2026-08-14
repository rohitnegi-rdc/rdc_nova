"""Unit tests for Nova V2's reusable Google GenAI client."""

import asyncio
import os
import sys
import types
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from tools import main_pipe


class _FakeModels:
    def __init__(self):
        self.calls = []

    async def generate_content(self, *, model, contents, config):
        self.calls.append(
            {
                "model": model,
                "contents": contents,
                "config": config,
            }
        )
        if "evidence validation step" in contents:
            text = '{"accepted_ranks":[1],"rejected_ranks":[],"reason":"relevant"}'
        else:
            text = (
                '{"decision":"in_domain","confidence":0.99,'
                '"domain_area":"ids_edge","matched_terms":["ids"],"reason":"supported"}'
            )
        return SimpleNamespace(text=text, usage_metadata=None)


class _FakeAsyncClient:
    def __init__(self):
        self.models = _FakeModels()
        self.close_calls = 0

    async def aclose(self):
        self.close_calls += 1


class _FakeClient:
    def __init__(self, api_key):
        self.api_key = api_key
        self.aio = _FakeAsyncClient()
        self.close_calls = 0

    def close(self):
        self.close_calls += 1


class _ClientFactory:
    def __init__(self):
        self.clients = []

    def __call__(self, *, api_key):
        client = _FakeClient(api_key)
        self.clients.append(client)
        return client


def _google_modules(factory):
    google_module = types.ModuleType("google")
    google_module.__path__ = []
    genai_module = types.ModuleType("google.genai")
    genai_module.Client = factory
    google_module.genai = genai_module
    return {
        "google": google_module,
        "google.genai": genai_module,
    }


def _chunk():
    return {
        "rank": 1,
        "text": "IDS Edge supports parallel silo feeding.",
        "metadata": {"name": "IDS guide", "file_id": "kb-1"},
        "distance": 0.1,
    }


class GeminiClientReuseTests(unittest.IsolatedAsyncioTestCase):
    async def test_domain_and_validation_share_one_client(self):
        factory = _ClientFactory()
        pipe = main_pipe.Pipe()

        with (
            patch.dict(os.environ, {"GEMINI_API_KEY": "key-a"}),
            patch.dict(sys.modules, _google_modules(factory)),
        ):
            domain = await pipe._domain_check("How do I configure IDS Edge?")
            validated, _ = await pipe._validate("How do I configure IDS Edge?", [_chunk()])

        self.assertEqual(domain["decision"], "in_domain")
        self.assertEqual(validated, [_chunk()])
        self.assertEqual(len(factory.clients), 1)
        self.assertEqual(len(factory.clients[0].aio.models.calls), 2)

    async def test_concurrent_first_use_creates_only_one_client(self):
        factory = _ClientFactory()
        pipe = main_pipe.Pipe()

        with (
            patch.dict(os.environ, {"GEMINI_API_KEY": "key-a"}),
            patch.dict(sys.modules, _google_modules(factory)),
        ):
            clients = await asyncio.gather(
                *(pipe._get_gemini_client() for _ in range(10))
            )

        self.assertEqual(len(factory.clients), 1)
        self.assertTrue(all(client is clients[0] for client in clients))

    async def test_api_key_change_replaces_and_closes_cached_client(self):
        factory = _ClientFactory()
        pipe = main_pipe.Pipe()

        with patch.dict(os.environ, {"GEMINI_API_KEY": "key-a"}), patch.dict(
            sys.modules, _google_modules(factory)
        ):
            first = await pipe._get_gemini_client()
            os.environ["GEMINI_API_KEY"] = "key-b"
            second = await pipe._get_gemini_client()

        self.assertIsNot(first, second)
        self.assertEqual([client.api_key for client in factory.clients], ["key-a", "key-b"])
        self.assertEqual(first.aio.close_calls, 1)
        self.assertEqual(first.close_calls, 1)
        self.assertEqual(second.aio.close_calls, 0)
        self.assertEqual(second.close_calls, 0)


if __name__ == "__main__":
    unittest.main()
