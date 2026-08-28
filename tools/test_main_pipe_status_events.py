"""Focused contract tests for Tara Ops V2's Open WebUI progress events."""

import inspect
import sys
import types
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from tools import main_pipe


class _TraceStub:
    def __init__(self, *args, **kwargs):
        pass

    async def start(self, inputs):
        pass

    async def begin_step(self, name, inputs, **kwargs):
        return None

    async def end_step(self, handle, outputs, **kwargs):
        pass

    async def step(self, name, inputs, outputs, **kwargs):
        pass

    async def measure(self, name, inputs, operation, output_builder=None, usage_builder=None, **kwargs):
        result = await operation()
        if output_builder:
            built = output_builder(result)
            if inspect.isawaitable(built):
                await built
        return result

    async def finish(self, outputs, error=None):
        pass


class _ModelParams:
    def model_dump(self):
        return {"system": "Test Tara Ops prompt", "temperature": 0.25}


class _Models:
    @staticmethod
    async def get_model_by_id(model_id):
        return SimpleNamespace(
            id="nova",
            base_model_id="gemini-test",
            params=_ModelParams(),
            meta=SimpleNamespace(
                model_dump=lambda: {
                    "knowledge": [{"id": "must-not-be-forwarded"}],
                    "toolIds": ["must-not-be-forwarded"],
                }
            ),
        )


class _UserModel:
    @staticmethod
    def model_validate(value):
        return value


def _request():
    config = SimpleNamespace(
        ENABLE_RAG_HYBRID_SEARCH=False,
        RAG_RERANKING_ENGINE="",
        RAG_RERANKING_MODEL="",
        TOP_K_RERANKER=None,
        RELEVANCE_THRESHOLD=None,
    )
    state = SimpleNamespace(RERANKING_FUNCTION=None, config=config)
    return SimpleNamespace(app=SimpleNamespace(state=state))


def _chunk(rank=1, source="KB Guide", file_id="kb-1", source_type="knowledge_base"):
    return {
        "rank": rank,
        "text": "Grounded test evidence.",
        "distance": 0.1,
        "metadata": {
            "name": source,
            "file_id": file_id,
            "source_type": source_type,
        },
    }


class PipeStatusEventTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.pipe = main_pipe.Pipe()
        self.pipe.valves.LANGCHAIN_API_KEY = ""
        self.events = []
        self.retrieve_calls = 0
        self.nova_request = None

        async def emitter(event):
            self.events.append(event)

        self.emitter = emitter

    async def _run(
        self,
        *,
        domain,
        retrieved,
        validated=None,
        web_chunks=None,
        fail_retrieve=False,
        emitter=True,
        query="Running two BINs simultaneously",
    ):
        async def domain_check(query):
            return domain

        async def retrieve(request, query):
            self.retrieve_calls += 1
            if fail_retrieve:
                raise RuntimeError("sensitive internal failure")
            return retrieved, {"usage_status": "test"}

        async def validate(query, chunks):
            accepted = chunks if validated is None else validated
            return accepted, {
                "decision": {
                    "accepted_ranks": [item["rank"] for item in accepted],
                    "rejected_ranks": [],
                    "reason": "test",
                },
                "raw_response": "{}",
            }

        async def web_search(request, query, user, include_content, trace=None, event_emitter=None):
            await self.pipe._emit_status(event_emitter, "web_search", "Searching the web")
            await self.pipe._emit_status(event_emitter, "web_filter", "Reviewing web sources")
            await self.pipe._emit_status(event_emitter, "web_validate", "Validating web evidence")
            accepted = web_chunks or []
            return accepted, {
                "enabled": True,
                "validation": {
                    "decision": {
                        "accepted_ranks": [item["rank"] for item in accepted],
                        "rejected_ranks": [],
                        "reason": "test",
                    }
                },
            }

        async def effective(body, nova_model, user):
            return {"model": "gemini-test", "stream": True, "messages": body["messages"]}

        async def nova(request, downstream, user):
            self.nova_request = downstream
            return [], "Grounded answer [1]", {"total_tokens": 12}

        async def nova_usage(usage, *, model):
            return {"usage_status": "provider_reported"}

        self.pipe._domain_check = domain_check
        self.pipe._retrieve = retrieve
        self.pipe._validate = validate
        self.pipe._web_search = web_search
        self.pipe._effective_nova_request = effective
        self.pipe._nova = nova
        self.pipe._nova_usage = nova_usage

        models_module = types.ModuleType("open_webui.models.models")
        models_module.Models = _Models
        users_module = types.ModuleType("open_webui.models.users")
        users_module.UserModel = _UserModel
        body = {
            "messages": [
                {
                    "role": "user",
                    "content": query,
                }
            ],
            "stream": True,
        }

        with (
            patch.object(main_pipe, "TraceSession", _TraceStub),
            patch.dict(
                sys.modules,
                {
                    "open_webui.models.models": models_module,
                    "open_webui.models.users": users_module,
                },
            ),
        ):
            return [
                item
                async for item in self.pipe.pipe(
                    body,
                    __user__={"id": "test-user"},
                    __request__=_request(),
                    __event_emitter__=self.emitter if emitter else None,
                )
            ]

    def _actions(self):
        return [event["data"]["action"] for event in self.events]

    def test_pipe_declares_openwebui_event_emitter(self):
        parameters = inspect.signature(main_pipe.Pipe.pipe).parameters
        self.assertIn("__event_emitter__", parameters)
        self.assertIn("__message_id__", parameters)

    async def test_pipe_can_replace_preexisting_native_sources(self):
        sources = [{"source": {"id": "kb-1", "name": "KB Guide"}, "document": ["Evidence"]}]

        await self.pipe._replace_message_sources(self.emitter, "response-1", sources)

        self.assertEqual(
            self.events,
            [
                {
                    "type": "chat:outlet",
                    "data": {
                        "messages": [
                            {
                                "id": "response-1",
                                "sources": sources,
                            }
                        ]
                    },
                }
            ],
        )

    def test_native_openwebui_rag_wrapper_is_reduced_to_original_query(self):
        wrapped = (
            "### Task: Respond to the user query using the provided context, incorporating inline citations.\n"
            "### Guidelines:\n- Only cite supplied sources.\n"
            "<context><source id=\"1\">Untrusted native web context</source></context>\n"
            "Running Two BINs/SILOs Simultaneously (Coarse Feeding / Parallel Feed)"
        )
        body = {"messages": [{"role": "user", "content": wrapped}]}

        self.assertEqual(
            self.pipe._query(body),
            "Running Two BINs/SILOs Simultaneously (Coarse Feeding / Parallel Feed)",
        )
        downstream = self.pipe._build_nova_body(body, "PIPE_EVIDENCE", "knowledge_base")
        sent = downstream["messages"][-1]["content"]
        self.assertTrue(sent.startswith("Running Two BINs/SILOs Simultaneously"))
        self.assertNotIn("Untrusted native web context", sent)
        self.assertIn("PIPE_EVIDENCE", sent)

    async def test_provider_request_targets_base_model_and_removes_rag_controls(self):
        calls = {}

        def apply_params(params, body):
            calls["params"] = params
            body.update(params)
            return body

        async def apply_system(system, body, metadata, user):
            calls["system"] = system
            calls["metadata"] = metadata
            body["messages"].insert(0, {"role": "system", "content": system})
            return body

        payload_module = types.ModuleType("open_webui.utils.payload")
        payload_module.apply_model_params_to_body_openai = apply_params
        payload_module.apply_system_prompt_to_body = apply_system
        nova_model = await _Models.get_model_by_id("nova")
        body = {
            "model": "nova",
            "messages": [{"role": "user", "content": "Question with PIPE_EVIDENCE"}],
            "stream": True,
            "stream_options": {"include_usage": True},
            "metadata": {"variables": {"name": "Operator"}, "files": ["native-kb"]},
            "files": [{"id": "native-kb"}],
            "tool_ids": ["native-tool"],
            "tools": [{"type": "function"}],
            "features": {"web_search": True},
            "filter_ids": ["native-filter"],
        }

        with patch.dict(sys.modules, {"open_webui.utils.payload": payload_module}):
            effective = await self.pipe._effective_nova_request(body, nova_model, {"id": "user"})

        self.assertEqual(effective["model"], "gemini-test")
        self.assertEqual(calls["system"], "Test Tara Ops prompt")
        self.assertEqual(effective["temperature"], 0.25)
        self.assertIn("PIPE_EVIDENCE", effective["messages"][-1]["content"])
        for forbidden in (
            "metadata",
            "files",
            "tool_ids",
            "tools",
            "features",
            "filter_ids",
            "knowledge",
        ):
            self.assertNotIn(forbidden, effective)

    async def test_provider_request_requires_nova_base_model(self):
        nova_model = SimpleNamespace(
            id="nova",
            base_model_id=None,
            params=_ModelParams(),
        )
        payload_module = types.ModuleType("open_webui.utils.payload")
        payload_module.apply_model_params_to_body_openai = lambda params, body: body

        async def apply_system(system, body, metadata, user):
            return body

        payload_module.apply_system_prompt_to_body = apply_system

        with patch.dict(sys.modules, {"open_webui.utils.payload": payload_module}):
            with self.assertRaisesRegex(RuntimeError, "base model"):
                await self.pipe._effective_nova_request(
                    {"model": "nova", "messages": [{"role": "user", "content": "Question"}]},
                    nova_model,
                    {"id": "user"},
                )

    async def test_nova_dispatch_bypasses_provider_system_prompt_reapplication(self):
        calls = {}

        async def generate_chat_completion(request, body, user, **kwargs):
            calls["body"] = body
            calls["kwargs"] = kwargs
            return "provider answer"

        chat_module = types.ModuleType("open_webui.utils.chat")
        chat_module.generate_chat_completion = generate_chat_completion

        with patch.dict(sys.modules, {"open_webui.utils.chat": chat_module}):
            await self.pipe._nova(
                _request(),
                {"model": "gemini-test", "messages": [{"role": "user", "content": "Question"}]},
                {"id": "user"},
            )

        self.assertEqual(calls["body"]["model"], "gemini-test")
        self.assertTrue(calls["kwargs"]["bypass_system_prompt"])

    async def test_knowledge_base_path_reports_live_stages(self):
        chunk = _chunk()
        output = await self._run(
            domain={"decision": "in_domain", "confidence": 0.99},
            retrieved=[chunk],
        )

        self.assertEqual(
            self._actions(),
            [
                "domain_check",
                "knowledge_search",
                "sources_retrieved",
                "validate_kb",
                "build_context",
                "nova_generate",
                "complete",
            ],
        )
        self.assertTrue(self.events[-1]["data"]["done"])
        self.assertIn("Grounded answer [1]", output)
        self.assertTrue(any(isinstance(item, dict) and item.get("event", {}).get("type") == "source" for item in output))
        self.assertEqual(self.retrieve_calls, 1)
        self.assertEqual(self.nova_request["model"], "gemini-test")

    async def test_web_fallback_reports_web_only_when_used(self):
        self.pipe.valves.ENABLE_WEB_SEARCH = True
        output = await self._run(
            domain={"decision": "in_domain", "confidence": 0.99},
            retrieved=[],
            web_chunks=[_chunk(source="RDC About", file_id="https://rdc.in/about", source_type="web_search")],
        )

        self.assertEqual(
            self._actions(),
            [
                "domain_check",
                "knowledge_search",
                "sources_retrieved",
                "web_search",
                "web_filter",
                "web_validate",
                "build_context",
                "nova_generate",
                "complete",
            ],
        )
        self.assertIn("Grounded answer [1]", output)

    async def test_out_of_domain_stops_before_retrieval(self):
        output = await self._run(
            domain={"decision": "out_of_domain", "confidence": 0.99},
            retrieved=[],
            query="What is the capital of France?",
        )

        self.assertEqual(self._actions(), ["domain_check", "out_of_domain"])
        self.assertTrue(self.events[-1]["data"]["done"])
        self.assertEqual(output, [self.pipe.OUT_OF_DOMAIN_MESSAGE])

    async def test_high_confidence_out_of_domain_with_generic_domain_word_stops_before_retrieval(
        self,
    ):
        output = await self._run(
            domain={"decision": "out_of_domain", "confidence": 0.99},
            retrieved=[_chunk()],
            query="Give me a concrete example of a Python decorator.",
        )

        self.assertEqual(self.retrieve_calls, 0)
        self.assertEqual(self._actions(), ["domain_check", "out_of_domain"])
        self.assertEqual(output, [self.pipe.OUT_OF_DOMAIN_MESSAGE])

    async def test_strong_domain_identifier_still_protects_against_false_rejection(self):
        output = await self._run(
            domain={"decision": "out_of_domain", "confidence": 0.99},
            retrieved=[_chunk()],
            query="How do I configure IDS Edge?",
        )

        self.assertEqual(self.retrieve_calls, 1)
        self.assertIn("Grounded answer [1]", output)

    async def test_greeting_only_returns_llm_response_before_retrieval(self):
        greeting = (
            "Hello! 👋 I’m Tara Ops, your RDC Concrete support assistant. "
            "How can I help you today?"
        )
        output = await self._run(
            domain={
                "decision": "greeting_only",
                "confidence": 0.99,
                "greeting_response": greeting,
            },
            retrieved=[],
            query="Hello",
        )

        self.assertEqual(self._actions(), ["domain_check", "greeting"])
        self.assertTrue(self.events[-1]["data"]["done"])
        self.assertEqual(self.retrieve_calls, 0)
        self.assertEqual(output, [greeting])
        self.assertFalse(any(isinstance(item, dict) for item in output))

    async def test_greeting_with_question_continues_through_rag(self):
        chunk = _chunk()
        output = await self._run(
            domain={"decision": "in_domain", "confidence": 0.99},
            retrieved=[chunk],
            query="Hello, why is my IDS ticket not showing?",
        )

        self.assertEqual(self.retrieve_calls, 1)
        self.assertIn("Grounded answer [1]", output)
        self.assertIn("knowledge_search", self._actions())
        self.assertNotIn("greeting", self._actions())

    async def test_error_closes_progress_without_exposing_exception(self):
        output = await self._run(
            domain={"decision": "in_domain", "confidence": 0.99},
            retrieved=[],
            fail_retrieve=True,
        )

        self.assertEqual(self._actions(), ["domain_check", "knowledge_search", "error"])
        self.assertTrue(self.events[-1]["data"]["done"])
        self.assertTrue(self.events[-1]["data"]["error"])
        self.assertNotIn("sensitive internal failure", str(self.events))
        self.assertIn("RuntimeError", output[0])

    async def test_missing_or_failed_emitter_never_breaks_the_answer(self):
        chunk = _chunk()
        output = await self._run(
            domain={"decision": "in_domain", "confidence": 0.99},
            retrieved=[chunk],
            emitter=False,
        )
        self.assertIn("Grounded answer [1]", output)

        async def broken_emitter(event):
            raise ConnectionError("browser disconnected")

        await self.pipe._emit_status(broken_emitter, "test", "Testing status")

    async def test_internal_openwebui_task_bypasses_rag_and_progress(self):
        downstream_seen = {}

        async def must_not_run(*args, **kwargs):
            raise AssertionError("Internal Open WebUI tasks must bypass the RAG pipeline")

        async def nova(request, downstream, user):
            downstream_seen.update(downstream)
            return [], '{"follow_ups":["How do I configure the second silo?"]}', {}

        self.pipe._domain_check = must_not_run
        self.pipe._retrieve = must_not_run
        self.pipe._web_search = must_not_run
        self.pipe._nova = nova

        async def effective(body, nova_model, user):
            return {
                "model": nova_model.base_model_id,
                "stream": True,
                "messages": body["messages"],
            }

        self.pipe._effective_nova_request = effective

        users_module = types.ModuleType("open_webui.models.users")
        users_module.UserModel = _UserModel
        models_module = types.ModuleType("open_webui.models.models")
        models_module.Models = _Models
        body = {
            "model": "nova_v2.nova_v2",
            "messages": [
                {
                    "role": "user",
                    "content": "Generate follow-up questions for this chat",
                }
            ],
            "stream": False,
        }

        with patch.dict(
            sys.modules,
            {
                "open_webui.models.models": models_module,
                "open_webui.models.users": users_module,
            },
        ):
            output = [
                item
                async for item in self.pipe.pipe(
                    body,
                    __user__={"id": "test-user"},
                    __request__=_request(),
                    __event_emitter__=self.emitter,
                    __task__="follow_up_generation",
                )
            ]

        self.assertEqual(output, ['{"follow_ups":["How do I configure the second silo?"]}'])
        self.assertEqual(self.events, [])
        self.assertEqual(downstream_seen["model"], "gemini-test")
        self.assertTrue(downstream_seen["stream"])


if __name__ == "__main__":
    unittest.main()
