"""
title: Nova V2
author: RDC Concrete
version: 2.2.0
description: Grounded Knowledge Base Pipe with hierarchical LangSmith tracing.
requirements: google-genai, langsmith
"""

import asyncio
import copy
import inspect
import re
import json
import os
import time
from collections import defaultdict
from typing import Any, AsyncGenerator, Optional
from urllib.parse import urlparse

from pydantic import BaseModel, Field


DOMAIN_GATE_PROMPT = """You are the domain gate for Nova, the internal support assistant for RDC Concrete.

Classify the user's latest question as exactly one of:
- in_domain: clearly about the supported RDC/RMC/IDS/Oracle operational domain
- ambiguous: possibly related to the supported domain, but too short or underspecified
- out_of_domain: clearly unrelated to the supported domain

The supported domain includes:
1. Ready-Mix Concrete (RMC) as a product and process: concrete grades and mix
   designs; cement; water; fine and coarse aggregates; supplementary cementitious
   materials such as fly ash, silica fume or ultrafine; chemical admixtures; fibres;
   water-cement ratio; batching, mixing, weighing, dosing, loading, dispatch,
   delivery, quality, slump, strength, yield, moisture, plant, transit mixer, pump
   and production operations.
2. Raw-material and plant operations: raw-material codes, material master data,
   stock, storage, bins, silos, weighers, scales, gates, conveyors, screws,
   feeders, skip buckets, mixers, HMI, PLC, instruments, calibration, auto/manual
   feed, filling faults, overloads, alarms, event logs, maintenance and plant
   troubleshooting.
3. IDS / IDS Edge / Integrated Batching: IDS Edge or IDS batching configuration,
   products, mix-design mapping, BIN/SILO assignment, coarse feeding or parallel
   feeding, services, QC Control, ConfigBOM, IDS RDC Import Live Service, HMI/PLC
   connectivity, VPN, tickets, batch reports and integration errors.
4. Oracle ERP and connected RDC workflows: Oracle ERP/Fusion ERP/SCM when used
   for RDC operations, including sales orders, mix designs, FG codes, item/material
   codes, inventory, procurement, manufacturing/production, order fulfillment,
   reports and ERP-to-IDS integration. The question need not say Oracle if this
   operational context is obvious.
5. RDC Concrete itself, its plants, products, processes, internal terminology,
   support procedures and supplied Knowledge Base.
6. RDC Concrete company and corporate matters: company profile and history,
   RDC-specific business units, plants and offices, departments, leadership and
   organizational roles, approved corporate policies and procedures, HR/admin/IT
   processes, support ownership and contacts, internal announcements, training,
   procurement, sales, customer-service and other business workflows when they
   specifically concern RDC Concrete. Answer these only from approved company
   evidence; do not infer private or current corporate facts.

Decision rules:
- A question is in_domain when it clearly concerns any supported area, even if it
  does not contain RMC, RDC, IDS or Oracle.
- A domain term plus an operational action or symptom is normally in_domain. For
  example: activate three silos, water not taking in auto, gate overloaded, ticket
  not showing, or admixture dosing high.
- A short question containing a potentially domain-related word such as batch,
  plant, silo, bin, ticket, service, mixer, Oracle or concrete but lacking context
  is ambiguous, not out_of_domain. Ambiguous questions continue to retrieval.
- Questions about RDC Concrete as an organization or employer are in_domain even
  when they are not technical, for example questions about RDC departments,
  company policies, support contacts, plants, leadership, internal processes or
  corporate information. Generic corporate, HR, legal or business questions not
  tied to RDC Concrete remain out_of_domain.
- Mark out_of_domain only when the question is clearly unrelated to all supported
  areas and has no plausible RDC/RMC/IDS/Oracle operational interpretation.
- Do not answer, solve, browse, retrieve or cite anything in this step.

Return JSON only:
{"decision":"in_domain|ambiguous|out_of_domain","confidence":0.0,"domain_area":"rmc_product|raw_materials|batching|ids_edge|oracle_erp|corporate|rdc|none|unclear","matched_terms":[],"reason":"short explanation"}

Confidence is confidence in the classification, not confidence that the Knowledge
Base contains the answer. Low-confidence or malformed output must be treated as
ambiguous and allowed to continue to retrieval.
"""


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return default


def _read_value(value: Any, *names: str, default: Any = None) -> Any:
    """Read SDK objects and dictionaries without leaking provider-specific details."""
    for name in names:
        if isinstance(value, dict) and name in value:
            return value[name]
        if hasattr(value, name):
            return getattr(value, name)
    return default


class TraceSession:
    """One LangSmith parent run with visible, completed child steps."""

    def __init__(self, api_key: str = "", endpoint: str = "", project: str = ""):
        self.root = None
        self.client = None
        self.api_key = api_key
        self.endpoint = endpoint
        self.project = project
        self.error = None

    async def begin_step(
        self,
        name: str,
        inputs: dict[str, Any],
        run_type: str = "chain",
        metadata: Optional[dict[str, Any]] = None,
    ) -> Optional[dict[str, Any]]:
        """Open a child span before the operation it represents starts."""
        if self.root is None:
            return None
        try:
            extra = {"metadata": metadata} if metadata else None
            child = self.root.create_child(name=name, run_type=run_type, inputs=inputs, extra=extra)
            await asyncio.to_thread(child.post)
            return {"run": child, "started_at": time.perf_counter()}
        except Exception:
            return None

    async def end_step(
        self,
        handle: Optional[dict[str, Any]],
        outputs: dict[str, Any],
        error: Optional[str] = None,
        usage_metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        """Close a child span after its operation has completed."""
        if not handle or handle.get("ended"):
            return
        child = handle.get("run")
        if child is None:
            return
        try:
            duration_ms = round((time.perf_counter() - handle["started_at"]) * 1000, 1)
            traced_outputs = dict(outputs or {})
            traced_outputs.setdefault("duration_ms", duration_ms)
            traced_outputs.setdefault("timing_status", "error" if error else "measured")
            if usage_metadata:
                child.set(usage_metadata=usage_metadata)
            child.end(outputs=traced_outputs, error=error)
            await asyncio.to_thread(child.patch)
            handle["ended"] = True
        except Exception:
            return

    async def measure(
        self,
        name: str,
        inputs: dict[str, Any],
        operation: Any,
        output_builder: Any = None,
        usage_builder: Any = None,
        run_type: str = "chain",
        metadata: Optional[dict[str, Any]] = None,
    ) -> Any:
        """Run an operation inside a correctly timed LangSmith child span."""
        handle = await self.begin_step(name, inputs, run_type=run_type, metadata=metadata)
        try:
            result = await operation()
        except Exception as exc:
            await self.end_step(
                handle,
                {"error_type": type(exc).__name__, "error": str(exc)},
                error=type(exc).__name__,
            )
            raise
        outputs = output_builder(result) if output_builder else (result if isinstance(result, dict) else {"result": result})
        if inspect.isawaitable(outputs):
            outputs = await outputs
        usage_metadata = usage_builder(result) if usage_builder else None
        if inspect.isawaitable(usage_metadata):
            usage_metadata = await usage_metadata
        await self.end_step(handle, outputs, usage_metadata=usage_metadata)
        return result

    async def start(self, inputs: dict[str, Any]) -> None:
        key = self.api_key or os.getenv("LANGCHAIN_API_KEY", "")
        if not key:
            return
        try:
            from langsmith import Client
            from langsmith.run_trees import RunTree

            self.client = Client(
                api_url=self.endpoint or os.getenv("LANGCHAIN_ENDPOINT", "https://api.smith.langchain.com"),
                api_key=key,
            )
            self.root = RunTree(
                name="grounded-knowledge-pipe",
                run_type="chain",
                inputs=inputs,
                project_name=self.project or os.getenv("LANGCHAIN_PROJECT", "open-webui-knowledge-pipe"),
                serialized={"type": "openwebui_pipe"},
                extra={
                    "metadata": {
                        "pipeline": "grounded-knowledge-pipe",
                        "cost_tracking": "langsmith_provider_usage_and_pricing",
                    }
                },
                ls_client=self.client,
            )
            await asyncio.to_thread(self.root.post)
        except Exception as exc:
            self.error = f"{type(exc).__name__}: {exc}"
            self.root = None
            self.client = None

    async def step(
        self,
        name: str,
        inputs: dict[str, Any],
        outputs: dict[str, Any],
        error: Optional[str] = None,
        run_type: str = "chain",
        metadata: Optional[dict[str, Any]] = None,
        usage_metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        handle = await self.begin_step(name, inputs, run_type=run_type, metadata=metadata)
        snapshot_outputs = dict(outputs or {})
        snapshot_outputs.setdefault("timing_status", "skipped" if snapshot_outputs.get("skipped") else "snapshot")
        await self.end_step(handle, snapshot_outputs, error=error, usage_metadata=usage_metadata)

    async def finish(self, outputs: dict[str, Any], error: Optional[str] = None) -> None:
        if self.root is None:
            return
        try:
            self.root.end(outputs=outputs, error=error)
            await asyncio.to_thread(self.root.patch)
        except Exception:
            return


class Pipe:
    PROVIDER_REQUEST_KEYS = frozenset(
        {
            "messages",
            "stream",
            "stream_options",
            "temperature",
            "top_p",
            "min_p",
            "max_tokens",
            "max_completion_tokens",
            "frequency_penalty",
            "presence_penalty",
            "reasoning_effort",
            "seed",
            "stop",
            "logit_bias",
            "response_format",
            "n",
            "user",
            "service_tier",
            "verbosity",
        }
    )
    RAG_CONTROL_KEYS = frozenset(
        {
            "metadata",
            "files",
            "file_ids",
            "knowledge",
            "knowledge_ids",
            "tool_ids",
            "tools",
            "features",
            "filter_ids",
            "folder_id",
            "skill_ids",
            "terminal_id",
            "web_search",
        }
    )
    OUT_OF_DOMAIN_MESSAGE = (
        "I can only assist with RDC Concrete company, operations, batching, and ERP queries. "
        "For other assistance, please contact Admin support at 82918 91159 or 86570 49242."
    )

    class Valves(BaseModel):
        GEMINI_API_KEY: str = Field(
            default="",
            description="Gemini API key used for domain checking, validation, and cost counting.",
            json_schema_extra={"input": {"type": "password"}},
        )
        LANGCHAIN_API_KEY: str = Field(
            default="",
            description="LangSmith API key for hierarchical traces.",
            json_schema_extra={"input": {"type": "password"}},
        )
        LANGCHAIN_ENDPOINT: str = Field(
            default="https://api.smith.langchain.com",
            description="LangSmith endpoint.",
        )
        LANGCHAIN_PROJECT: str = Field(
            default="open-webui-knowledge-pipe",
            description="LangSmith project name.",
        )
        NOVA_MODEL: str = Field(
            default="nova",
            description="Open WebUI model ID that owns Nova's configured system prompt.",
        )
        VALIDATION_MODEL: str = Field(
            default="gemini-3.5-flash-lite",
            description="Gemini model used for domain and evidence validation.",
        )
        KNOWLEDGE_BASE_ID: str = Field(
            default="8bf6c71f-2ff8-4165-bbac-84408c7e2551",
            description="Open WebUI Knowledge Base ID queried by the pipe.",
        )
        TOP_K: int = Field(default=8, description="Number of Knowledge Base chunks to retrieve.")
        MAX_CONTEXT_CHARS: int = Field(default=24000, description="Maximum evidence context sent to Nova.")
        MIN_SOURCES: int = Field(default=1, description="Minimum validated sources before web fallback.")
        TRACE_INCLUDE_CONTENT: bool = Field(
            default=True,
            description="Include retrieved text and prompts in LangSmith. Disable for sensitive content.",
        )
        ENABLE_WEB_SEARCH: bool = Field(
            default=False,
            description="Allow targeted web fallback when the Knowledge Base is insufficient.",
        )
        WEB_SEARCH_ENGINE: str = Field(default="duckduckgo", description="Open WebUI web search engine.")
        WEB_SEARCH_RESULT_COUNT: int = Field(default=5, description="Maximum web candidates to validate.")
        WEB_SEARCH_MAX_CONTENT_CHARS: int = Field(
            default=12000,
            description="Maximum characters loaded from each web page.",
        )
        ENABLE_DOMAIN_CHECK: bool = Field(
            default=True,
            description="Run the domain classifier before retrieval.",
        )
        DOMAIN_CHECK_MODEL: str = Field(
            default="gemini-3.5-flash-lite",
            description="Gemini model used for the domain classifier.",
        )
        DOMAIN_OUT_OF_DOMAIN_THRESHOLD: float = Field(
            default=0.90,
            description="Confidence required to stop an obviously out-of-domain request.",
        )
        NOVA_PROVIDER: str = Field(default="google_genai", description="Provider label used in cost traces.")

    def __init__(self):
        self.valves = self.Valves()

    @staticmethod
    async def _emit_status(
        event_emitter: Any,
        action: str,
        description: str,
        *,
        done: bool = False,
        hidden: bool = False,
        **details: Any,
    ) -> None:
        """Emit a user-safe Open WebUI status without affecting the answer path."""
        if not callable(event_emitter):
            return

        safe_details = {
            key: value
            for key, value in details.items()
            if key in {"query", "count", "chunk_count", "source_count", "origin", "error"}
        }
        event = {
            "type": "status",
            "data": {
                "action": action,
                "description": description,
                "done": done,
                "hidden": hidden,
                **safe_details,
            },
        }
        try:
            result = event_emitter(event)
            if inspect.isawaitable(result):
                await result
        except Exception:
            # A closed browser/socket must never break retrieval or generation.
            return

    @staticmethod
    async def _replace_message_sources(
        event_emitter: Any,
        message_id: Optional[str],
        sources: list[dict[str, Any]],
    ) -> None:
        """Replace sources already attached by native middleware with Pipe evidence."""
        if not callable(event_emitter) or not message_id:
            return
        try:
            result = event_emitter(
                {
                    "type": "chat:outlet",
                    "data": {
                        "messages": [
                            {
                                "id": message_id,
                                "sources": sources,
                            }
                        ]
                    },
                }
            )
            if inspect.isawaitable(result):
                await result
        except Exception:
            return

    def pipes(self) -> list[dict[str, str]]:
        return [{"id": "nova_v2", "name": "Nova V2"}]

    def _setting(self, name: str) -> Any:
        value = os.getenv(name, getattr(self.valves, name, ""))
        if isinstance(value, str) and value.lower() in {"true", "false"}:
            return value.lower() == "true"
        return value

    def _api_key(self) -> str:
        key = self._setting("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY", "")
        if not key:
            raise RuntimeError("GEMINI_API_KEY is not configured")
        return key

    @staticmethod
    def _ls_model_metadata(provider: str, model: str) -> dict[str, str]:
        return {
            "ls_provider": provider,
            "ls_model_name": str(model or "unknown").removeprefix("models/"),
        }

    def _gemini_usage(
        self,
        response: Any,
        *,
        model: str,
    ) -> dict[str, Any]:
        """Forward Gemini-reported usage to LangSmith without estimating or pricing it."""
        raw = getattr(response, "usage_metadata", None)
        prompt_tokens = _as_int(_read_value(raw, "prompt_token_count", "promptTokenCount"))
        candidates_tokens = _as_int(_read_value(raw, "candidates_token_count", "candidatesTokenCount"))
        thoughts_tokens = _as_int(_read_value(raw, "thoughts_token_count", "thoughtsTokenCount"))
        output_tokens = candidates_tokens + thoughts_tokens
        if not output_tokens:
            output_tokens = _as_int(_read_value(raw, "response_token_count", "responseTokenCount"))
        total_tokens = _as_int(_read_value(raw, "total_token_count", "totalTokenCount"))
        reported = bool(prompt_tokens or output_tokens or total_tokens)
        if not reported:
            return {"usage_status": "unavailable", "usage_model": model}

        total_tokens = total_tokens or prompt_tokens + output_tokens

        usage = {
            "input_tokens": prompt_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
        }
        if thoughts_tokens:
            usage["output_token_details"] = {
                "text": candidates_tokens,
                "reasoning": thoughts_tokens,
            }
        return {
            "usage_status": "provider_reported",
            "usage_metadata": usage,
        }

    async def _nova_usage(
        self,
        usage: Optional[dict[str, Any]],
        *,
        model: str,
    ) -> dict[str, Any]:
        """Forward provider-reported Nova usage; never count, estimate, or price locally."""
        normalized = usage or {}
        input_tokens = _as_int(normalized.get("input_tokens"))
        output_tokens = _as_int(normalized.get("output_tokens"))
        total_tokens = _as_int(normalized.get("total_tokens"))
        if not (input_tokens or output_tokens or total_tokens):
            return {"usage_status": "unavailable", "usage_model": model}

        normalized = {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens or input_tokens + output_tokens,
        }
        return {
            "usage_status": "provider_reported",
            "usage_metadata": normalized,
        }

    @staticmethod
    def _domain_signals(query: str) -> list[str]:
        """Find broad safety signals so a classifier cannot reject an RMC question."""
        text = query.lower()
        patterns = (
            ("rdc", r"\brdc\b"),
            ("ready_mix", r"\bready[ -]?mix(?:ed)?\b"),
            ("concrete", r"\bconcrete\b"),
            ("cement", r"\bcement\b"),
            ("admixture", r"\badmixture(?:s)?\b"),
            ("aggregate", r"\baggregates?\b"),
            ("batching", r"\bbatch(?:ing|ed)?\b"),
            ("mix_design", r"\bmix[ -]?design\b"),
            ("raw_material", r"\braw[ -]?material(?:s)?\b"),
            ("ids", r"\bids(?:[ -]?edge)?\b"),
            ("integrated_batching", r"\bintegrated[ -]?batching\b"),
            ("oracle_erp", r"\boracle(?:[ -]?(?:fusion|cloud))?[ -]?erp\b|\berp\b"),
            ("sales_order", r"\bsales[ -]?order\b|\bso\b(?=.*\b(?:erp|ids|ticket|offline|order|show|block|submit))"),
            ("fg_code", r"\bfg[ -]?code\b"),
            ("bin_silo", r"\b(?:bin|bins|silo|silos)\b"),
            ("hmi_plc", r"\b(?:hmi|plc)\b"),
            ("configbom", r"\bconfigbom\b"),
            ("event_viewer", r"\bevent[ -]?viewer\b"),
            ("dosage", r"\bdos(?:e|ing|age|ed)\b"),
            ("weigher", r"\b(?:weigh(?:er|ing)?|scale)\b"),
        )
        return [name for name, pattern in patterns if re.search(pattern, text)]

    async def _domain_check(self, query: str) -> dict[str, Any]:
        """Classify scope, failing open to retrieval whenever classification is uncertain."""
        signals = self._domain_signals(query)
        if not bool(self._setting("ENABLE_DOMAIN_CHECK")):
            return {
                "decision": "in_domain",
                "confidence": 0.0,
                "domain_area": "unclear",
                "matched_terms": signals,
                "reason": "Domain check disabled; request allowed to retrieval.",
                "enabled": False,
                "prompt": DOMAIN_GATE_PROMPT,
            }

        try:
            from google import genai

            client = genai.Client(api_key=self._api_key())
            model = self._setting("DOMAIN_CHECK_MODEL") or self._setting("VALIDATION_MODEL")
            prompt = f"{DOMAIN_GATE_PROMPT}\n\nUSER QUESTION:\n{query}"
            response = await client.aio.models.generate_content(
                model=model,
                contents=prompt,
                config={"temperature": 0, "response_mime_type": "application/json"},
            )
            raw = (response.text or "").strip()
            usage_report = self._gemini_usage(response, model=model)
            decision = json.loads(raw)
            label = str(decision.get("decision", "ambiguous")).lower()
            if label not in {"in_domain", "ambiguous", "out_of_domain"}:
                label = "ambiguous"
            try:
                confidence = float(decision.get("confidence", 0.0))
            except (TypeError, ValueError):
                confidence = 0.0
            confidence = max(0.0, min(1.0, confidence))
            matched_terms = decision.get("matched_terms")
            if not isinstance(matched_terms, list):
                matched_terms = []
            report = {
                "decision": label,
                "confidence": confidence,
                "domain_area": decision.get("domain_area", "unclear"),
                "matched_terms": matched_terms,
                "reason": decision.get("reason", ""),
                "raw_response": raw,
                "enabled": True,
                "model": model,
                "prompt": DOMAIN_GATE_PROMPT,
                **usage_report,
            }
            # A model must never reject a query containing supported vocabulary.
            # Route it through retrieval so the KB or a clarifying response can decide.
            if label == "out_of_domain" and signals:
                report["decision"] = "ambiguous"
                report["safety_override"] = "domain_signal_present"
                report["matched_terms"] = sorted(set(matched_terms + signals))
                report["reason"] = "Classifier said out_of_domain, but supported-domain terms were detected; routed to retrieval."
            return report
        except Exception as exc:
            return {
                "decision": "ambiguous",
                "confidence": 0.0,
                "domain_area": "unclear",
                "matched_terms": signals,
                "reason": f"Domain classifier unavailable; routed to retrieval: {type(exc).__name__}",
                "enabled": True,
                "error_type": type(exc).__name__,
                "prompt": DOMAIN_GATE_PROMPT,
            }

    @staticmethod
    def _unwrap_user_query(content: str) -> str:
        """Remove Open WebUI's native RAG wrapper while preserving ordinary input."""
        stripped = content.strip()
        is_native_rag_wrapper = (
            stripped.startswith("### Task:")
            and "Respond to the user query using the provided context" in stripped
            and "<context>" in stripped
            and "</context>" in stripped
        )
        if not is_native_rag_wrapper:
            return content

        query = stripped.rsplit("</context>", 1)[1].strip()
        for prefix in ("### User Query:", "User Query:", "QUERY:"):
            if query.startswith(prefix):
                query = query[len(prefix) :].strip()
                break
        return query or content

    @classmethod
    def _query(cls, body: dict[str, Any]) -> str:
        for message in reversed(body.get("messages") or []):
            if message.get("role") == "user":
                content = message.get("content", "")
                content = content if isinstance(content, str) else str(content)
                return cls._unwrap_user_query(content)
        return ""

    async def _retrieve(
        self,
        request: Any,
        query: str,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Use Open WebUI retrieval while exposing embedding-call diagnostics to LangSmith."""
        from open_webui.retrieval.utils import query_collection

        config = getattr(request.app.state, "config", None)
        engine = str(self._config_value(config, "RAG_EMBEDDING_ENGINE", "") or "")
        model = str(self._config_value(config, "RAG_EMBEDDING_MODEL", "") or "")
        original_embedding = request.app.state.EMBEDDING_FUNCTION
        embedding_calls: list[dict[str, Any]] = []

        async def observed_embedding(values: Any, prefix: Any = None, user: Any = None) -> Any:
            result = await original_embedding(values, prefix=prefix, user=user)
            texts = values if isinstance(values, list) else [values]
            embedding_calls.append(
                {
                    "status": "completed",
                    "engine": engine or "sentence_transformers",
                    "model": model or "provider_default",
                    "text_count": len(texts),
                    "usage_status": "not_reported_by_openwebui_embedding_adapter",
                }
            )
            return result

        result = await query_collection(
            request=request,
            collection_names=[self._setting("KNOWLEDGE_BASE_ID")],
            queries=[query],
            embedding_function=observed_embedding,
            k=int(self._setting("TOP_K")),
        )
        documents = (result.get("documents") or [[]])[0]
        metadatas = (result.get("metadatas") or [[]])[0]
        distances = (result.get("distances") or [[]])[0]
        chunks = [
            {"rank": index, "text": text, "metadata": metadata or {}, "distance": distance}
            for index, (text, metadata, distance) in enumerate(zip(documents, metadatas, distances), 1)
            if text
        ]
        embedding_report = {
            "engine": engine or "sentence_transformers",
            "model": model,
            "call_count": len(embedding_calls),
            "calls": embedding_calls,
            "usage_status": "not_reported_by_openwebui_embedding_adapter",
        }
        return chunks, embedding_report

    @staticmethod
    def _chunk_details(chunks: list[dict[str, Any]], include_content: bool = True) -> list[dict[str, Any]]:
        details = []
        for chunk in chunks:
            metadata = chunk["metadata"]
            detail = {
                "rank": chunk["rank"],
                "distance": chunk.get("distance"),
                "source": metadata.get("name") or metadata.get("filename") or metadata.get("source"),
                "file_id": metadata.get("file_id"),
                "page": metadata.get("page"),
                "metadata": metadata,
            }
            if include_content:
                detail["content"] = chunk["text"]
            details.append(detail)
        return details

    @staticmethod
    def _web_candidate_details(
        candidates: list[dict[str, Any]], include_content: bool = True
    ) -> list[dict[str, Any]]:
        """Serialize pre-validation web candidates without assuming KB chunk metadata."""
        details: list[dict[str, Any]] = []
        for candidate in candidates:
            detail = {
                "rank": candidate.get("rank"),
                "title": candidate.get("title"),
                "url": candidate.get("url"),
                "queries": candidate.get("queries", []),
                "content_source": candidate.get("content_source", "page"),
            }
            if include_content:
                detail["content"] = candidate.get("content", "")
            details.append(detail)
        return details

    @staticmethod
    def _sources(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        grouped: dict[str, dict[str, Any]] = defaultdict(
            lambda: {"document": [], "metadata": [], "distances": []}
        )
        for chunk in chunks:
            metadata = dict(chunk["metadata"])
            file_id = metadata.get("file_id") or metadata.get("id") or metadata.get("source") or "unknown"
            name = metadata.get("name") or metadata.get("filename") or metadata.get("source") or "Unknown source"
            grouped[str(file_id)]["document"].append(chunk["text"])
            grouped[str(file_id)]["metadata"].append({**metadata, "file_id": file_id, "name": name, "source": name})
            if chunk.get("distance") is not None:
                grouped[str(file_id)]["distances"].append(chunk["distance"])
        return [
            {
                "source": {"id": key if key != "unknown" else None, "name": value["metadata"][0]["name"]},
                "document": value["document"],
                "metadata": value["metadata"],
                **({"distances": value["distances"]} if value["distances"] else {}),
            }
            for key, value in grouped.items()
        ]

    @staticmethod
    def _context(chunks: list[dict[str, Any]], limit: int) -> tuple[str, list[int]]:
        parts: list[str] = []
        included: list[int] = []
        source_ids: dict[str, int] = {}
        size = 0
        for index, chunk in enumerate(chunks, 1):
            metadata = chunk["metadata"]
            source = metadata.get("name") or metadata.get("filename") or metadata.get("source") or "Unknown source"
            source_type = metadata.get("source_type", "knowledge_base")
            origin = "WEB_SEARCH_EVIDENCE" if source_type == "web_search" else "KNOWLEDGE_BASE_EVIDENCE"
            source_key = str(
                metadata.get("file_id")
                or metadata.get("id")
                or metadata.get("source")
                or source
            )
            if source_key not in source_ids:
                source_ids[source_key] = len(source_ids) + 1
            source_id = source_ids[source_key]
            item = f"<source id=\"{source_id}\" origin=\"{origin}\" name=\"{source}\">\n{chunk['text'].strip()}\n</source>"
            if size + len(item) > limit:
                continue
            parts.append(item)
            included.append(index)
            size += len(item)
        return "\n\n".join(parts), included

    async def _validate(
        self,
        query: str,
        chunks: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Use Gemini as a transparent evidence validator; preserve raw decision for tracing."""
        from google import genai

        evidence = "\n\n".join(f"RANK {c['rank']}: {c['text']}" for c in chunks)
        prompt = f"""You are an evidence validation step for a RAG system.
Return JSON only with this schema: {{\"accepted_ranks\": [1], \"rejected_ranks\": [], \"reason\": \"...\"}}.
Accept a chunk only if it directly helps answer the question. Do not answer the question.

QUESTION: {query}
EVIDENCE:\n{evidence}"""
        client = genai.Client(api_key=self._api_key())
        response = await client.aio.models.generate_content(
            model=self._setting("VALIDATION_MODEL"),
            contents=prompt,
            config={"temperature": 0, "response_mime_type": "application/json"},
        )
        raw = (response.text or "").strip()
        usage_report = self._gemini_usage(response, model=self._setting("VALIDATION_MODEL"))
        try:
            decision = json.loads(raw)
        except json.JSONDecodeError:
            decision = {"accepted_ranks": [c["rank"] for c in chunks], "rejected_ranks": [], "reason": "Invalid validator JSON; fail-open for diagnosis."}
        accepted = set(decision.get("accepted_ranks", []))
        validated = [chunk for chunk in chunks if chunk["rank"] in accepted]
        return validated, {"decision": decision, "raw_response": raw, **usage_report}

    @staticmethod
    def _config_value(config: Any, name: str, default: Any = None) -> Any:
        value = getattr(config, name, default)
        return getattr(value, "value", value)

    @staticmethod
    def _web_queries(query: str) -> list[str]:
        """Use the user's query directly to avoid injecting unrelated domain terms."""
        return [
            query
        ]

    @staticmethod
    def _is_corporate_query(query: str) -> bool:
        query_text = str(query or "").lower()
        has_rdc = bool(re.search(r"\brdc(?:\s+concrete)?\b", query_text)) or "rdcconcrete" in query_text.replace(" ", "")
        corporate_terms = (
            "ceo",
            "chief executive",
            "managing director",
            "leadership",
            "company",
            "corporate",
            "organization",
            "organisation",
            "head office",
            "department",
            "policy",
            "history",
            "founder",
            "employee",
            "employer",
            "human resources",
            "hr ",
        )
        return has_rdc and any(term in query_text for term in corporate_terms)

    @staticmethod
    def _web_result_dict(result: Any, query: str) -> dict[str, Any]:
        return {
            "url": getattr(result, "link", "") or "",
            "title": getattr(result, "title", "") or "",
            "snippet": getattr(result, "snippet", "") or "",
            "query": query,
        }

    @staticmethod
    def _web_prefilter(candidate: dict[str, Any], query: str) -> Optional[str]:
        """Reject unrelated pages while allowing RDC corporate evidence."""
        url = candidate.get("url", "")
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return "invalid_or_non_http_url"

        text = " ".join(
            str(candidate.get(field, ""))
            for field in ("url", "title", "snippet")
        ).lower()
        blocked_page_markers = (
            "just a moment...",
            "enable javascript and cookies to continue",
            "checking your browser",
            "cf-chl-",
            "cloudflare ray id",
            "please verify you are a human",
        )
        if any(marker in text for marker in blocked_page_markers):
            return "blocked_or_challenge_page"
        has_ids = bool(re.search(r"\bids\b", text))
        has_oracle_erp = any(
            marker in text
            for marker in ("oracle erp", "oracle fusion erp", "oracle enterprise resource planning")
        )
        has_rdc_company = (
            bool(re.search(r"\brdc(?:\s+concrete)?\b", text))
            or "rdcconcrete" in text.replace(" ", "")
            or "rdc.in" in text
        )
        if Pipe._is_corporate_query(query):
            corporate_terms = (
                "ceo",
                "chief executive",
                "managing director",
                "leadership",
                "company",
                "corporate",
                "organization",
                "organisation",
                "head office",
                "department",
                "policy",
                "history",
                "founder",
                "employee",
                "employer",
                "human resources",
            )
            if not has_rdc_company:
                return "missing_rdc_corporate_marker"
            if not any(term in text for term in corporate_terms):
                return "missing_corporate_marker"
            return None
        if not has_ids and not has_oracle_erp:
            return "missing_ids_or_oracle_marker"
        if not any(term in text for term in ("batch", "silo", "bin", "feed", "concrete", "erp")):
            return "missing_batching_or_erp_marker"
        query_text = query.lower()
        if any(term in query_text for term in ("silo", "silos", "bin", "bins", "feed", "feeding")) and not any(
            term in text for term in ("silo", "silos", "bin", "bins", "feed", "feeding", "feeder")
        ):
            return "does_not_match_requested_silo_or_feed_topic"
        if any(term in text for term in ("rocket silo", "federated learning", "video game", "animal feed")):
            return "unrelated_silo_domain"
        return None

    async def _validate_web(
        self,
        query: str,
        candidates: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Require direct support from operational or RDC corporate evidence."""
        if not candidates:
            return [], {
                "decision": {"accepted_ranks": [], "rejected_ranks": [], "reason": "No web candidates passed prefilter."},
                "raw_response": "",
            }

        evidence = "\n\n".join(
            f"RANK {candidate['rank']}\nTITLE: {candidate['title']}\nURL: {candidate['url']}\nCONTENT:\n{candidate['content']}"
            for candidate in candidates
        )
        if self._is_corporate_query(query):
            validation_rules = """You are a strict web-evidence validator for RDC Concrete corporate questions.
Return JSON only with this schema: {\"accepted_ranks\": [1], \"rejected_ranks\": [2], \"reason\": \"...\"}.
Accept a page only when BOTH conditions are true:
1. It explicitly concerns RDC Concrete as a company, including its leadership, organization, offices, policies, history, or corporate operations.
2. It directly supports the user's question.
Reject generic company, CEO, construction, concrete, or other-vendor pages that do not clearly concern RDC Concrete.
Do not answer the question."""
        else:
            validation_rules = """You are a strict web-evidence validator for an IDS Batching and Oracle ERP assistant.
Return JSON only with this schema: {{\"accepted_ranks\": [1], \"rejected_ranks\": [2], \"reason\": \"...\"}}.
Accept a page only when BOTH conditions are true:
1. It explicitly concerns IDS/IDS Batching or Oracle ERP in an operational batching context.
2. It directly supports the user's question.
Reject generic silo, BIN, concrete, animal-feed, gaming, research, or other-vendor pages even if they sound similar.
Do not answer the question.
"""
        prompt = f"""{validation_rules}

QUESTION: {query}
WEB EVIDENCE:\n{evidence}"""
        from google import genai

        client = genai.Client(api_key=self._api_key())
        response = await client.aio.models.generate_content(
            model=self._setting("VALIDATION_MODEL"),
            contents=prompt,
            config={"temperature": 0, "response_mime_type": "application/json"},
        )
        raw = (response.text or "").strip()
        usage_report = self._gemini_usage(response, model=self._setting("VALIDATION_MODEL"))
        try:
            decision = json.loads(raw)
        except json.JSONDecodeError:
            decision = {
                "accepted_ranks": [],
                "rejected_ranks": [candidate["rank"] for candidate in candidates],
                "reason": "Invalid web validator JSON; fail-closed for external evidence.",
            }
        accepted = {rank for rank in decision.get("accepted_ranks", []) if isinstance(rank, int)}
        validated = [candidate for candidate in candidates if candidate["rank"] in accepted]
        return validated, {"decision": decision, "raw_response": raw, **usage_report}

    async def _web_search(
        self,
        request: Any,
        query: str,
        user: Any,
        include_content: bool,
        trace: Optional[TraceSession] = None,
        event_emitter: Any = None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Search, filter/fetch, and validate web evidence with timed trace stages."""
        from open_webui.retrieval.web.utils import get_web_loader
        from open_webui.routers.retrieval import search_web

        config = getattr(request.app.state, "config", None)
        engine = self._setting("WEB_SEARCH_ENGINE") or self._config_value(config, "WEB_SEARCH_ENGINE", "duckduckgo")
        count = int(self._setting("WEB_SEARCH_RESULT_COUNT"))
        queries = self._web_queries(query)
        report: dict[str, Any] = {
            "enabled": True,
            "engine": engine,
            "queries": queries,
            "search_results": [],
            "prefilter_rejections": [],
            "fetch_errors": [],
            "fetch_warnings": [],
        }

        async def run_search() -> dict[str, Any]:
            search_batches = await asyncio.gather(
                *(search_web(request, engine, search_query, user) for search_query in queries),
                return_exceptions=True,
            )
            candidates: list[dict[str, Any]] = []
            errors: list[dict[str, Any]] = []
            for search_query, batch in zip(queries, search_batches):
                if isinstance(batch, Exception):
                    errors.append({"query": search_query, "stage": "search", "error": str(batch)})
                    continue
                for result in batch or []:
                    candidates.append(self._web_result_dict(result, search_query))
            return {"candidates": candidates, "errors": errors}

        await self._emit_status(
            event_emitter,
            "web_search",
            "Searching the web",
        )
        search_result = await (
            trace.measure(
                "04-web-search",
                {"query": query, "engine": engine, "queries": queries},
                run_search,
                output_builder=lambda result: {
                    "enabled": True,
                    "result_count": len(result["candidates"]),
                    "search_results": [
                        {key: value for key, value in candidate.items() if key != "snippet" or include_content}
                        for candidate in result["candidates"]
                    ],
                    "errors": result["errors"],
                    "timing_status": "measured",
                },
            )
            if trace
            else run_search()
        )
        report["search_results"] = [
            {key: value for key, value in candidate.items() if key != "snippet" or include_content}
            for candidate in search_result["candidates"]
        ]
        report["fetch_errors"].extend(search_result["errors"])

        async def run_filter() -> dict[str, Any]:
            candidates_by_url: dict[str, dict[str, Any]] = {}
            prefilter_rejections: list[dict[str, Any]] = []
            for candidate in search_result["candidates"]:
                reason = self._web_prefilter(candidate, query)
                if reason:
                    prefilter_rejections.append({**candidate, "reason": reason})
                    continue
                existing = candidates_by_url.get(candidate["url"])
                if existing:
                    existing["queries"] = sorted(set(existing.get("queries", []) + [candidate["query"]]))
                else:
                    candidate["queries"] = [candidate["query"]]
                    candidates_by_url[candidate["url"]] = candidate

            candidates = list(candidates_by_url.values())[:count]
            urls = [candidate["url"] for candidate in candidates]
            docs_by_url: dict[str, str] = {}
            fetch_errors: list[dict[str, Any]] = []
            if urls:
                try:
                    loader = get_web_loader(
                        urls,
                        verify_ssl=self._config_value(config, "ENABLE_WEB_LOADER_SSL_VERIFICATION", True),
                        requests_per_second=self._config_value(config, "WEB_LOADER_CONCURRENT_REQUESTS", 2),
                        trust_env=self._config_value(config, "WEB_SEARCH_TRUST_ENV", True),
                    )
                    docs = await loader.aload()
                    docs_by_url = {
                        str(doc.metadata.get("source", "")): doc.page_content
                        for doc in docs
                        if doc.metadata.get("source")
                    }
                except Exception as exc:
                    fetch_errors.append({"stage": "page_load", "error": str(exc)})

            max_chars = int(self._setting("WEB_SEARCH_MAX_CONTENT_CHARS"))
            validator_candidates: list[dict[str, Any]] = []
            warnings: list[dict[str, Any]] = []
            for rank, candidate in enumerate(candidates, 1):
                page_content = docs_by_url.get(candidate["url"])
                content_source = "page"
                content = page_content or candidate.get("snippet", "")
                if page_content and self._web_prefilter(
                    {**candidate, "snippet": str(page_content)[:max_chars]}, query
                ) == "blocked_or_challenge_page":
                    content = candidate.get("snippet", "")
                    content_source = "search_snippet_fallback"
                    warnings.append(
                        {
                            "url": candidate["url"],
                            "stage": "page_load",
                            "warning": "Page returned a browser challenge; using the search-result snippet only.",
                        }
                    )
                if not content:
                    prefilter_rejections.append({**candidate, "rank": rank, "reason": "empty_page_content"})
                    continue
                content_candidate = {**candidate, "snippet": str(content)[:max_chars]}
                reason = self._web_prefilter(content_candidate, query)
                if reason:
                    prefilter_rejections.append({**candidate, "rank": rank, "reason": reason})
                    continue
                validator_candidates.append(
                    {
                        **candidate,
                        "rank": rank,
                        "content": str(content)[:max_chars],
                        "content_source": content_source,
                    }
                )
            return {
                "validator_candidates": validator_candidates,
                "prefilter_rejections": prefilter_rejections,
                "fetch_errors": fetch_errors,
                "fetch_warnings": warnings,
            }

        await self._emit_status(
            event_emitter,
            "web_filter",
            "Reviewing web sources",
        )
        filter_result = await (
            trace.measure(
                "05-web-filter",
                {"query": query, "candidate_count": len(search_result["candidates"])},
                run_filter,
                output_builder=lambda result: {
                    "prefilter_rejections": result["prefilter_rejections"],
                    "fetched_candidates": [
                        {
                            key: value
                            for key, value in candidate.items()
                            if key != "content" or include_content
                        }
                        for candidate in result["validator_candidates"]
                    ],
                    "fetch_errors": result["fetch_errors"],
                    "fetch_warnings": result["fetch_warnings"],
                },
            )
            if trace
            else run_filter()
        )
        report["prefilter_rejections"] = filter_result["prefilter_rejections"]
        report["fetch_errors"].extend(filter_result["fetch_errors"])
        report["fetch_warnings"] = filter_result["fetch_warnings"]
        validator_candidates = filter_result["validator_candidates"]

        async def run_validation() -> tuple[list[dict[str, Any]], dict[str, Any]]:
            return await self._validate_web(query, validator_candidates)

        await self._emit_status(
            event_emitter,
            "web_validate",
            "Validating web evidence",
        )
        validated, validation = await (
            trace.measure(
                "06-web-validate",
                {"query": query, "candidate_count": len(validator_candidates)},
                run_validation,
                output_builder=lambda result: {
                    "accepted": self._web_candidate_details(result[0], include_content),
                    "accepted_ranks": result[1].get("decision", {}).get("accepted_ranks", []),
                    "rejected_ranks": result[1].get("decision", {}).get("rejected_ranks", []),
                    **result[1],
                },
                usage_builder=lambda result: result[1].get("usage_metadata"),
                run_type="llm" if validator_candidates else "chain",
                metadata=self._ls_model_metadata("google_genai", self._setting("VALIDATION_MODEL"))
                if validator_candidates
                else None,
            )
            if trace
            else run_validation()
        )
        report["fetched_candidates"] = [
            {
                key: value
                for key, value in candidate.items()
                if key != "content" or include_content
            }
            for candidate in validator_candidates
        ]
        report["validation"] = validation
        web_chunks = [
            {
                "rank": candidate["rank"],
                "text": candidate["content"],
                "distance": None,
                "metadata": {
                    "file_id": candidate["url"],
                    "name": candidate["title"] or candidate["url"],
                    "source": candidate["url"],
                    "url": candidate["url"],
                    "link": candidate["url"],
                    "source_type": "web_search",
                    "search_queries": candidate.get("queries", []),
                    "content_source": candidate.get("content_source", "page"),
                },
            }
            for candidate in validated
        ]
        return web_chunks, report

    def _build_nova_body(self, body: dict[str, Any], context: str, evidence_origin: str) -> dict[str, Any]:
        """Build the exact request passed to Open WebUI's internal dispatcher."""
        downstream = copy.deepcopy(body)
        downstream["model"] = self._setting("NOVA_MODEL")
        downstream["stream"] = True
        downstream.setdefault("stream_options", {"include_usage": True})
        messages = downstream.get("messages") or []
        last_user = next((message for message in reversed(messages) if message.get("role") == "user"), None)
        if last_user is None:
            raise RuntimeError("No user message found")
        original_query = self._unwrap_user_query(str(last_user.get("content", "")))
        if self._is_corporate_query(original_query):
            downstream["messages"].insert(
                0,
                {
                    "role": "system",
                    "content": (
                        "Pipe routing result: this request is an in-domain RDC Concrete corporate question. "
                        "Treat RDC Concrete company, leadership, departments, offices, policies, and corporate "
                        "information as in-domain. Do not use the generic out-of-domain refusal for this request. "
                        "Answer only from the grounded evidence context; if it does not contain enough evidence, "
                        "say that the answer could not be verified."
                    ),
                },
            )
        evidence_instruction = {
            "none": "No validated web source was accepted. Do not say the answer came from web search and do not provide web citations.",
            "knowledge_base": "Clearly state that the answer is based on the Knowledge Base and cite the supporting Knowledge Base source IDs.",
            "web_search": "Clearly state that the answer uses web search and cite the supporting web source IDs.",
        }.get(evidence_origin, "Do not claim an evidence origin that is not present in the context.")
        last_user["content"] = (
            f"{original_query}\n\n"
            "Grounded evidence context:\n"
            f"{context}\n\n"
            "Citation rules: cite factual claims supported by the context with inline numeric citations such as [1] or [2]. "
            "Use a citation only when the matching <source id=\"N\"> exists; never invent a citation. "
            "Use the origin labels exactly as provided. Do not present WEB_SEARCH_EVIDENCE as Knowledge Base evidence. "
            f"If the context says NO_RELEVANT_EVIDENCE, answer using your configured system prompt but clearly state that no validated Knowledge Base or web evidence was found. {evidence_instruction}"
        )
        return downstream

    async def _effective_nova_request(
        self,
        body: dict[str, Any],
        nova_model: Any,
        user: Any,
    ) -> dict[str, Any]:
        """Build the sanitized request sent to Nova's underlying provider model.

        Nova is a workspace preset. Its system prompt and generation parameters
        are retained, while model knowledge, tools, files, and web controls are
        deliberately excluded so this Pipe remains the only RAG owner.
        """
        if not nova_model:
            raise RuntimeError(f"Nova model preset '{self._setting('NOVA_MODEL')}' was not found")

        preset_id = str(getattr(nova_model, "id", None) or self._setting("NOVA_MODEL"))
        base_model_id = str(getattr(nova_model, "base_model_id", None) or "").strip()
        if not base_model_id or base_model_id == preset_id:
            raise RuntimeError(f"Nova model preset '{preset_id}' does not have a valid base model")

        from open_webui.utils.payload import apply_model_params_to_body_openai, apply_system_prompt_to_body

        metadata = copy.deepcopy(body.get("metadata"))
        effective = {
            key: copy.deepcopy(value)
            for key, value in body.items()
            if key in self.PROVIDER_REQUEST_KEYS and value is not None
        }
        effective.setdefault("messages", [])
        effective["stream"] = True
        effective.setdefault("stream_options", {"include_usage": True})

        params = nova_model.params.model_dump() if getattr(nova_model, "params", None) else {}
        system = params.pop("system", None)
        effective = apply_model_params_to_body_openai(params, effective)
        effective = await apply_system_prompt_to_body(system, effective, metadata, user)
        for key in self.RAG_CONTROL_KEYS:
            effective.pop(key, None)
        effective["model"] = base_model_id
        return effective

    @staticmethod
    def _stream_text(event: Any) -> str:
        """Extract assistant text from one or more OpenAI-compatible SSE lines."""
        if not isinstance(event, str):
            return ""
        text_parts: list[str] = []
        for line in event.splitlines():
            if not line.startswith("data: ") or line.strip() == "data: [DONE]":
                continue
            try:
                payload = json.loads(line[6:].strip())
            except json.JSONDecodeError:
                continue
            for choice in payload.get("choices", []):
                delta = choice.get("delta", {}) or {}
                text = delta.get("content") or (choice.get("message", {}) or {}).get("content")
                if text:
                    text_parts.append(text)
        return "".join(text_parts)

    @staticmethod
    def _stream_usage(event: Any) -> dict[str, Any]:
        """Extract the final OpenAI-compatible usage object from an SSE event."""
        if not isinstance(event, str):
            return {}
        latest: dict[str, Any] = {}
        for line in event.splitlines():
            if not line.startswith("data: ") or line.strip() == "data: [DONE]":
                continue
            try:
                payload = json.loads(line[6:].strip())
            except json.JSONDecodeError:
                continue
            usage = payload.get("usage")
            if isinstance(usage, dict):
                latest = usage
        if not latest:
            return {}
        input_tokens = _as_int(latest.get("input_tokens") or latest.get("prompt_tokens"))
        output_tokens = _as_int(latest.get("output_tokens") or latest.get("completion_tokens"))
        total_tokens = _as_int(latest.get("total_tokens"), input_tokens + output_tokens)
        return {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
        }

    async def _nova(self, request: Any, downstream: dict[str, Any], user: Any) -> tuple[list[Any], str, dict[str, Any]]:
        """Call Nova's resolved provider model without reapplying preset behavior."""
        from open_webui.utils.chat import generate_chat_completion

        response = await generate_chat_completion(
            request,
            downstream,
            user,
            bypass_system_prompt=True,
        )
        events: list[Any] = []
        text_parts: list[str] = []
        usage: dict[str, Any] = {}
        if hasattr(response, "body_iterator"):
            async for data in response.body_iterator:
                event = data.decode("utf-8", errors="replace") if isinstance(data, bytes) else data
                events.append(event)
                text_parts.append(self._stream_text(event))
                usage.update(self._stream_usage(event))
        else:
            events.append(response)
            text_parts.append(str(response))
        return events, "".join(text_parts), usage

    async def pipe(
        self,
        body: dict[str, Any],
        __user__: Optional[dict[str, Any]] = None,
        __request__: Any = None,
        __event_emitter__: Any = None,
        __task__: Optional[str] = None,
        __message_id__: Optional[str] = None,
    ) -> AsyncGenerator[Any, None]:
        if __task__:
            if __request__ is None:
                raise RuntimeError("Open WebUI task dispatch requires a request context")

            # Title, tag, emoji, and follow-up generation prompts are Open WebUI
            # control tasks, not user questions. Sending them through domain/RAG
            # can leak the control prompt into retrieval or web search. Delegate
            # them directly to Nova and let the outer task endpoint consume the
            # clean text result.
            from open_webui.models.models import Models
            from open_webui.models.users import UserModel

            task_user = UserModel.model_validate(__user__) if isinstance(__user__, dict) else __user__
            task_body = copy.deepcopy(body)
            task_body["model"] = self._setting("NOVA_MODEL")
            task_body["stream"] = True
            task_body.setdefault("stream_options", {"include_usage": True})
            task_model = await Models.get_model_by_id(self._setting("NOVA_MODEL"))
            task_provider_body = await self._effective_nova_request(task_body, task_model, task_user)
            _, task_output, _ = await self._nova(__request__, task_provider_body, task_user)
            if task_output:
                yield task_output
            return

        query = self._query(body)
        if not query:
            await self._emit_status(
                __event_emitter__,
                "missing_input",
                "No user question was provided",
                done=True,
                error=True,
            )
            yield "No user question was provided."
            return
        if __request__ is None:
            await self._emit_status(
                __event_emitter__,
                "error",
                "The request context is unavailable",
                done=True,
                error=True,
            )
            yield "The Pipe requires an Open WebUI request context for native retrieval and citations."
            return

        trace = TraceSession(
            api_key=self._setting("LANGCHAIN_API_KEY"),
            endpoint=self._setting("LANGCHAIN_ENDPOINT"),
            project=self._setting("LANGCHAIN_PROJECT"),
        )
        final_output: dict[str, Any] = {}
        try:
            web_enabled = bool(self._setting("ENABLE_WEB_SEARCH"))
            await trace.start(
                {
                    "query": query,
                    "knowledge_base_id": self._setting("KNOWLEDGE_BASE_ID"),
                    "nova_model": self._setting("NOVA_MODEL"),
                    "rag_owner": "pipe",
                    "web_search_enabled": web_enabled,
                    "domain_check_enabled": bool(self._setting("ENABLE_DOMAIN_CHECK")),
                    "domain_check_model": self._setting("DOMAIN_CHECK_MODEL"),
                    "cost_tracking": "langsmith_provider_usage_and_pricing",
                }
            )
            include_content = bool(self._setting("TRACE_INCLUDE_CONTENT"))
            await self._emit_status(
                __event_emitter__,
                "domain_check",
                "Checking request domain",
            )
            domain_check = await trace.measure(
                "00-domain-check",
                {
                    "query": query,
                    "prompt": DOMAIN_GATE_PROMPT if include_content else "<prompt omitted>",
                },
                lambda: self._domain_check(query),
                output_builder=lambda result: result,
                usage_builder=lambda result: result.get("usage_metadata"),
                run_type="llm",
                metadata=self._ls_model_metadata("google_genai", self._setting("DOMAIN_CHECK_MODEL")),
            )
            try:
                out_of_domain_threshold = float(self._setting("DOMAIN_OUT_OF_DOMAIN_THRESHOLD"))
            except (TypeError, ValueError):
                out_of_domain_threshold = 0.90
            if (
                domain_check.get("decision") == "out_of_domain"
                and float(domain_check.get("confidence", 0.0)) >= out_of_domain_threshold
                and not self._domain_signals(query)
            ):
                skip_reason = "High-confidence out_of_domain result; retrieval and generation bypassed."
                for name in (
                    "01-retrieve",
                    "02-rerank",
                    "03-validate-kb",
                    "04-web-search",
                    "05-web-filter",
                    "06-web-validate",
                    "07-build-context",
                    "08-nova-input",
                    "09-nova-output",
                ):
                    await trace.step(name, {"query": query}, {"skipped": True, "reason": skip_reason})
                final_output = {
                    "status": "out_of_domain",
                    "answer": self.OUT_OF_DOMAIN_MESSAGE,
                    "sources": [],
                    "citation_count": 0,
                    "domain_check": domain_check,
                }
                await trace.step("10-finalize", {"query": query}, final_output)
                await self._replace_message_sources(
                    __event_emitter__,
                    __message_id__,
                    [],
                )
                await self._emit_status(
                    __event_emitter__,
                    "out_of_domain",
                    "Request is outside Nova's supported domain",
                    done=True,
                )
                yield self.OUT_OF_DOMAIN_MESSAGE
                return
            await self._emit_status(
                __event_emitter__,
                "knowledge_search",
                "Searching the Knowledge Base",
                query=query,
            )
            chunks, embedding_report = await trace.measure(
                "01-retrieve",
                {"query": query, "knowledge_base_id": self._setting("KNOWLEDGE_BASE_ID")},
                lambda: self._retrieve(__request__, query),
                output_builder=lambda result: {
                    "chunk_count": len(result[0]),
                    "retrieval_call_count": 1,
                    "rag_owner": "pipe",
                    "chunks": self._chunk_details(result[0], include_content),
                    "embedding_usage": result[1],
                },
                run_type="retriever",
            )
            retrieved_sources = self._sources(chunks)
            await self._emit_status(
                __event_emitter__,
                "sources_retrieved",
                "Knowledge Base retrieval completed",
                count=len(retrieved_sources),
                source_count=len(retrieved_sources),
                chunk_count=len(chunks),
            )

            validated: list[dict[str, Any]] = []
            validation: dict[str, Any] = {
                "decision": {"accepted_ranks": [], "rejected_ranks": [], "reason": "No Knowledge Base chunks retrieved."},
                "raw_response": "",
            }
            if chunks:
                # query_collection returns the final ranked order. If hybrid search is enabled,
                # its configured reranker has already been applied inside Open WebUI.
                reranker = getattr(__request__.app.state, "RERANKING_FUNCTION", None)
                config = getattr(__request__.app.state, "config", None)
                hybrid_enabled = bool(self._config_value(config, "ENABLE_RAG_HYBRID_SEARCH", False))
                reranker_config = {
                    "hybrid_search_enabled": hybrid_enabled,
                    "reranker_configured": bool(reranker),
                    "reranking_engine": self._config_value(config, "RAG_RERANKING_ENGINE", ""),
                    "reranking_model": self._config_value(config, "RAG_RERANKING_MODEL", ""),
                    "top_k_reranker": self._config_value(config, "TOP_K_RERANKER", None),
                    "relevance_threshold": self._config_value(config, "RELEVANCE_THRESHOLD", None),
                }
                ranks = [c["rank"] for c in chunks]
                rerank_handle = await trace.begin_step(
                    "02-rerank",
                    {"input_ranks": ranks, **reranker_config},
                )
                rerank_output = {
                    "input_ranks": ranks,
                    "output_ranks": ranks,
                    "ordered_chunks": self._chunk_details(chunks, include_content),
                    "reranker_config": reranker_config,
                    "timing_status": "snapshot",
                    "note": "query_collection returned this final order. Distances are retrieval return values; Open WebUI does not expose a separate reranker score here.",
                }
                await trace.end_step(rerank_handle, rerank_output)
                await self._emit_status(
                    __event_emitter__,
                    "validate_kb",
                    "Validating Knowledge Base evidence",
                    chunk_count=len(chunks),
                    source_count=len(retrieved_sources),
                )
                validated, validation = await trace.measure(
                    "03-validate-kb",
                    {"query": query, "chunks": self._chunk_details(chunks, include_content)},
                    lambda: self._validate(query, chunks),
                    output_builder=lambda result: {
                        "accepted": self._chunk_details(result[0], include_content),
                        "rejected_ranks": [c["rank"] for c in chunks if c not in result[0]],
                        **result[1],
                    },
                    usage_builder=lambda result: result[1].get("usage_metadata"),
                    run_type="llm",
                    metadata=self._ls_model_metadata("google_genai", self._setting("VALIDATION_MODEL")),
                )
            else:
                await trace.step(
                    "02-rerank",
                    {"input_ranks": [], "skipped": True},
                    {"output_ranks": [], "skipped": True, "reason": "No Knowledge Base chunks retrieved."},
                )
            if not chunks:
                await trace.step(
                    "03-validate-kb",
                    {"query": query, "chunks": []},
                    {"accepted": [], "rejected_ranks": [], **validation, "skipped": True, "reason": "No Knowledge Base chunks retrieved."},
                )

            kb_sources = self._sources(validated)
            web_chunks: list[dict[str, Any]] = []
            web_report: dict[str, Any]
            web_validation: dict[str, Any] = {}
            if len(kb_sources) < int(self._setting("MIN_SOURCES")):
                if web_enabled:
                    try:
                        from open_webui.models.users import UserModel

                        web_user = UserModel.model_validate(__user__) if isinstance(__user__, dict) else __user__
                        web_chunks, web_report = await self._web_search(
                            __request__,
                            query,
                            web_user,
                            include_content,
                            trace=trace,
                            event_emitter=__event_emitter__,
                        )
                        web_validation = web_report.get("validation", {})
                    except Exception as exc:
                        web_report = {
                            "enabled": True,
                            "error": f"{type(exc).__name__}: {exc}",
                            "queries": self._web_queries(query),
                        }
                        await trace.step(
                            "web-fallback-error",
                            {"query": query, "queries": web_report["queries"]},
                            {"enabled": True, "reason": "Web search failed; no external evidence accepted.", "error": web_report["error"]},
                            error=type(exc).__name__,
                        )
                else:
                    web_report = {"enabled": False, "reason": "disabled_by_valve"}
                    await trace.step(
                        "04-web-search",
                        {"query": query, "enabled": False},
                        {"enabled": False, "skipped": True, "reason": "ENABLE_WEB_SEARCH is false."},
                    )
                    await trace.step(
                        "05-web-filter",
                        {"enabled": False},
                        {"skipped": True, "reason": "Web search disabled."},
                    )
                    await trace.step(
                        "06-web-validate",
                        {"enabled": False},
                        {"skipped": True, "reason": "Web search disabled."},
                    )
            else:
                web_report = {"enabled": web_enabled, "skipped": True, "reason": "Knowledge Base evidence was sufficient."}
                for name in ("04-web-search", "05-web-filter", "06-web-validate"):
                    await trace.step(name, {"query": query}, {"skipped": True, "reason": web_report["reason"]})

            evidence_chunks = web_chunks if web_chunks else validated
            evidence_origin = "web_search" if web_chunks else ("knowledge_base" if validated else "none")
            await self._emit_status(
                __event_emitter__,
                "build_context",
                "Preparing grounded context",
                origin=evidence_origin,
            )
            context_handle = await trace.begin_step(
                "07-build-context",
                {"evidence_origin": evidence_origin, "validated_ranks": [c["rank"] for c in evidence_chunks]},
            )
            if evidence_chunks:
                context, included_ranks = self._context(evidence_chunks, int(self._setting("MAX_CONTEXT_CHARS")))
                citation_chunks = [
                    chunk
                    for index, chunk in enumerate(evidence_chunks, 1)
                    if index in included_ranks
                ]
            else:
                context = (
                    "<NO_RELEVANT_EVIDENCE>\n"
                    "No validated Knowledge Base evidence was found for this question.\n"
                    f"Web search status: {'enabled but no validated result' if web_enabled else 'disabled by configuration'}.\n"
                    "</NO_RELEVANT_EVIDENCE>"
                )
                included_ranks = []
                citation_chunks = []
            sources = self._sources(citation_chunks)
            await trace.end_step(
                context_handle,
                {
                    "included_ranks": included_ranks,
                    "evidence_origin": evidence_origin,
                    "context": context if include_content else "<content omitted>",
                    "context_chars": len(context),
                    "sources": sources,
                    "no_relevant_evidence": not bool(evidence_chunks),
                },
            )
            from open_webui.models.models import Models
            from open_webui.models.users import UserModel

            async def prepare_nova() -> tuple[Any, Any, Any, dict[str, Any], dict[str, Any]]:
                prepared_user = UserModel.model_validate(__user__) if isinstance(__user__, dict) else __user__
                prepared_model = await Models.get_model_by_id(self._setting("NOVA_MODEL"))
                prepared_system_prompt = None
                if prepared_model and prepared_model.params:
                    prepared_system_prompt = prepared_model.params.model_dump().get("system")
                prepared_body = self._build_nova_body(body, context, evidence_origin)
                prepared_effective_body = await self._effective_nova_request(
                    prepared_body, prepared_model, prepared_user
                )
                return (
                    prepared_user,
                    prepared_model,
                    prepared_system_prompt,
                    prepared_body,
                    prepared_effective_body,
                )

            user, nova_model, system_prompt, downstream_body, effective_body = await trace.measure(
                "08-nova-input",
                {"model": self._setting("NOVA_MODEL"), "evidence_origin": evidence_origin, "context": context if include_content else "<content omitted>"},
                prepare_nova,
                output_builder=lambda result: {
                    "nova_preset_id": self._setting("NOVA_MODEL"),
                    "resolved_base_model_id": result[4].get("model"),
                    "rag_owner": "pipe",
                    "native_rag_controls_forwarded": False,
                    "preset_request": result[3] if include_content else {"model": result[3]["model"], "stream": True, "message_count": len(result[3].get("messages", []))},
                    "effective_provider_request": result[4] if include_content else {"model": result[4].get("model"), "stream": result[4].get("stream"), "message_count": len(result[4].get("messages", []))},
                    "configured_system_prompt": result[2] or "<not found in model preset>",
                    "system_prompt_applied_by": "Nova V2 Pipe",
                    "evidence_origin": evidence_origin,
                    "web_search_report": web_report,
                    "note": "The effective provider request is sent directly to Nova's base model. Model knowledge, files, tools, and web controls are excluded.",
                },
            )
            nova_provider_model = str(effective_body.get("model") or self._setting("NOVA_MODEL"))
            nova_usage_report: dict[str, Any] = {}

            async def build_nova_output(result: tuple[list[Any], str, dict[str, Any]]) -> dict[str, Any]:
                nonlocal nova_usage_report
                nova_usage_report = await self._nova_usage(
                    result[2],
                    model=nova_provider_model,
                )
                return {
                    "event_count": len(result[0]),
                    "final_output": result[1],
                    "raw_events": result[0] if include_content else ["<events omitted>"],
                    **nova_usage_report,
                }

            await self._emit_status(
                __event_emitter__,
                "nova_generate",
                "Nova is generating the answer",
                origin=evidence_origin,
                source_count=len(sources),
            )
            events, nova_output, nova_raw_usage = await trace.measure(
                "09-nova-output",
                {
                    "model": nova_provider_model,
                    "nova_preset_id": self._setting("NOVA_MODEL"),
                    "rag_owner": "pipe",
                },
                lambda: self._nova(__request__, effective_body, user),
                output_builder=build_nova_output,
                usage_builder=lambda result: nova_usage_report.get("usage_metadata"),
                run_type="llm",
                metadata=self._ls_model_metadata(
                    str(self._setting("NOVA_PROVIDER") or "openwebui"),
                    nova_provider_model,
                ),
            )
            # The internal dispatcher returns provider SSE frames. Do not
            # forward those frames through the Pipe protocol: Open WebUI's
            # outer stream handler would parse and serialize them a second
            # time, which can introduce broken Markdown/word boundaries.
            # Emit one clean assistant payload instead.
            final_output = {
                "status": "success",
                "answer": nova_output,
                "sources": sources,
                "citation_count": len(sources),
                "evidence_origin": evidence_origin,
                "nova_preset_id": self._setting("NOVA_MODEL"),
                "resolved_base_model_id": nova_provider_model,
                "rag_owner": "pipe",
                "retrieval_call_count": 1,
            }
            finalize_handle = await trace.begin_step("10-finalize", {"answer": nova_output})
            await trace.end_step(finalize_handle, final_output)

            if nova_output:
                yield nova_output

            # Realtime chat handles citations as event-emitter events. A
            # top-level {"sources": [...]} object is ignored by the Pipe
            # middleware, so emit one source event per grouped file/source.
            for source in sources:
                yield {"event": {"type": "source", "data": source}}

            if nova_raw_usage:
                yield {"usage": nova_raw_usage}

            await self._replace_message_sources(
                __event_emitter__,
                __message_id__,
                sources,
            )

            await self._emit_status(
                __event_emitter__,
                "complete",
                "Answer completed",
                done=True,
                origin=evidence_origin,
                source_count=len(sources),
            )
        except Exception as exc:
            final_output = {
                "status": "error",
                "error_type": type(exc).__name__,
                "error": str(exc),
            }
            await trace.step("error", {"query": query}, final_output, error=type(exc).__name__)
            await self._replace_message_sources(
                __event_emitter__,
                __message_id__,
                [],
            )
            await self._emit_status(
                __event_emitter__,
                "error",
                "Unable to complete the request",
                done=True,
                error=True,
            )
            yield f"The Knowledge Base Pipe could not complete this request: {type(exc).__name__}."
        finally:
            await trace.finish(final_output)
