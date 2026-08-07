"""
title: Nova V2
author: RDC Concrete
version: 2.0.0
description: Grounded Knowledge Base Pipe with hierarchical LangSmith tracing.
requirements: google-genai, langsmith
"""

import asyncio
import copy
import re
import json
import os
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

Decision rules:
- A question is in_domain when it clearly concerns any supported area, even if it
  does not contain RMC, RDC, IDS or Oracle.
- A domain term plus an operational action or symptom is normally in_domain. For
  example: activate three silos, water not taking in auto, gate overloaded, ticket
  not showing, or admixture dosing high.
- A short question containing a potentially domain-related word such as batch,
  plant, silo, bin, ticket, service, mixer, Oracle or concrete but lacking context
  is ambiguous, not out_of_domain. Ambiguous questions continue to retrieval.
- Mark out_of_domain only when the question is clearly unrelated to all supported
  areas and has no plausible RDC/RMC/IDS/Oracle operational interpretation.
- Do not answer, solve, browse, retrieve or cite anything in this step.

Return JSON only:
{"decision":"in_domain|ambiguous|out_of_domain","confidence":0.0,"domain_area":"rmc_product|raw_materials|batching|ids_edge|oracle_erp|rdc|none|unclear","matched_terms":[],"reason":"short explanation"}

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
        if self.root is None:
            return
        try:
            extra = {"metadata": metadata} if metadata else None
            child = self.root.create_child(name=name, run_type=run_type, inputs=inputs, extra=extra)
            if usage_metadata:
                child.set(usage_metadata=usage_metadata)
            child.end(outputs=outputs, error=error)
            await asyncio.to_thread(child.post)
        except Exception:
            return

    async def finish(self, outputs: dict[str, Any], error: Optional[str] = None) -> None:
        if self.root is None:
            return
        try:
            self.root.end(outputs=outputs, error=error)
            await asyncio.to_thread(self.root.patch)
        except Exception:
            return


class Pipe:
    OUT_OF_DOMAIN_MESSAGE = (
        "I can only assist with RDC Concrete operations, batching, and ERP queries. "
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
    def _query(body: dict[str, Any]) -> str:
        for message in reversed(body.get("messages") or []):
            if message.get("role") == "user":
                content = message.get("content", "")
                return content if isinstance(content, str) else str(content)
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
        """Generate focused queries for the user's IDS/Oracle operating domain."""
        return [
            f'"IDS" batching "{query}"',
            f'"IDS" (BIN OR SILO) (feeding OR "parallel feed") "{query}"',
            f'"IDS" ("Oracle ERP" OR Oracle) batching "{query}"',
        ]

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
        """Reject obvious non-IDS/non-Oracle results before page loading."""
        url = candidate.get("url", "")
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return "invalid_or_non_http_url"

        text = " ".join(
            str(candidate.get(field, ""))
            for field in ("url", "title", "snippet")
        ).lower()
        has_ids = bool(re.search(r"\bids\b", text))
        has_oracle_erp = any(
            marker in text
            for marker in ("oracle erp", "oracle fusion erp", "oracle enterprise resource planning")
        )
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
        """Require explicit IDS/Oracle relevance and direct question support."""
        if not candidates:
            return [], {
                "decision": {"accepted_ranks": [], "rejected_ranks": [], "reason": "No web candidates passed prefilter."},
                "raw_response": "",
            }

        evidence = "\n\n".join(
            f"RANK {candidate['rank']}\nTITLE: {candidate['title']}\nURL: {candidate['url']}\nCONTENT:\n{candidate['content']}"
            for candidate in candidates
        )
        prompt = f"""You are a strict web-evidence validator for an IDS Batching and Oracle ERP assistant.
Return JSON only with this schema: {{\"accepted_ranks\": [1], \"rejected_ranks\": [2], \"reason\": \"...\"}}.
Accept a page only when BOTH conditions are true:
1. It explicitly concerns IDS/IDS Batching or Oracle ERP in an operational batching context.
2. It directly supports the user's question.
Reject generic silo, BIN, concrete, animal-feed, gaming, research, or other-vendor pages even if they sound similar.
Do not answer the question.

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
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Search using Open WebUI's configured engine and fail closed on web evidence."""
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
        }

        search_batches = await asyncio.gather(
            *(search_web(request, engine, search_query, user) for search_query in queries),
            return_exceptions=True,
        )
        candidates_by_url: dict[str, dict[str, Any]] = {}
        for search_query, batch in zip(queries, search_batches):
            if isinstance(batch, Exception):
                report["fetch_errors"].append({"query": search_query, "stage": "search", "error": str(batch)})
                continue
            for result in batch or []:
                candidate = self._web_result_dict(result, search_query)
                report["search_results"].append(
                    {key: value for key, value in candidate.items() if key != "snippet" or include_content}
                )
                reason = self._web_prefilter(candidate, query)
                if reason:
                    report["prefilter_rejections"].append({**candidate, "reason": reason})
                    continue
                existing = candidates_by_url.get(candidate["url"])
                if existing:
                    existing["queries"] = sorted(set(existing.get("queries", []) + [search_query]))
                else:
                    candidate["queries"] = [search_query]
                    candidates_by_url[candidate["url"]] = candidate

        candidates = list(candidates_by_url.values())[:count]
        urls = [candidate["url"] for candidate in candidates]
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
                docs_by_url = {}
                report["fetch_errors"].append({"stage": "page_load", "error": str(exc)})
        else:
            docs_by_url = {}

        max_chars = int(self._setting("WEB_SEARCH_MAX_CONTENT_CHARS"))
        validator_candidates = []
        for rank, candidate in enumerate(candidates, 1):
            content = docs_by_url.get(candidate["url"]) or candidate.get("snippet", "")
            if not content:
                report["prefilter_rejections"].append({**candidate, "rank": rank, "reason": "empty_page_content"})
                continue
            content_candidate = {**candidate, "snippet": str(content)[:max_chars]}
            reason = self._web_prefilter(content_candidate, query)
            if reason:
                report["prefilter_rejections"].append({**candidate, "rank": rank, "reason": reason})
                continue
            validator_candidates.append(
                {
                    **candidate,
                    "rank": rank,
                    "content": str(content)[:max_chars],
                }
            )

        validated, validation = await self._validate_web(query, validator_candidates)
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
        evidence_instruction = {
            "none": "No validated web source was accepted. Do not say the answer came from web search and do not provide web citations.",
            "knowledge_base": "Clearly state that the answer is based on the Knowledge Base and cite the supporting Knowledge Base source IDs.",
            "web_search": "Clearly state that the answer uses web search and cite the supporting web source IDs.",
        }.get(evidence_origin, "Do not claim an evidence origin that is not present in the context.")
        last_user["content"] = (
            f"{last_user.get('content', '')}\n\n"
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
        """Reproduce the model-preset transformation for trace inspection only.

        The returned copy is never sent. The real dispatcher applies the same
        transformations immediately before calling the configured provider.
        """
        effective = copy.deepcopy(body)
        if not nova_model:
            return effective

        from open_webui.utils.payload import apply_model_params_to_body_openai, apply_system_prompt_to_body

        params = nova_model.params.model_dump()
        system = params.pop("system", None)
        effective = apply_model_params_to_body_openai(params, effective)
        effective = await apply_system_prompt_to_body(system, effective, effective.get("metadata"), user)
        if nova_model.base_model_id:
            effective["model"] = nova_model.base_model_id
        effective.pop("metadata", None)
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
        """Call Open WebUI's dispatcher and capture the complete streamed Nova output."""
        from open_webui.utils.chat import generate_chat_completion

        response = await generate_chat_completion(request, downstream, user)
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
    ) -> AsyncGenerator[Any, None]:
        query = self._query(body)
        if not query:
            yield "No user question was provided."
            return
        if __request__ is None:
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
                    "web_search_enabled": web_enabled,
                    "domain_check_enabled": bool(self._setting("ENABLE_DOMAIN_CHECK")),
                    "domain_check_model": self._setting("DOMAIN_CHECK_MODEL"),
                    "cost_tracking": "langsmith_provider_usage_and_pricing",
                }
            )
            include_content = bool(self._setting("TRACE_INCLUDE_CONTENT"))
            domain_check = await self._domain_check(query)
            await trace.step(
                "00-domain-check",
                {
                    "query": query,
                    "prompt": DOMAIN_GATE_PROMPT if include_content else "<prompt omitted>",
                },
                domain_check,
                run_type="llm",
                metadata=self._ls_model_metadata("google_genai", domain_check.get("model", self._setting("DOMAIN_CHECK_MODEL"))),
                usage_metadata=domain_check.get("usage_metadata"),
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
                yield self.OUT_OF_DOMAIN_MESSAGE
                return
            chunks, embedding_report = await self._retrieve(__request__, query)
            await trace.step(
                "01-retrieve",
                {"query": query, "knowledge_base_id": self._setting("KNOWLEDGE_BASE_ID")},
                {
                    "chunk_count": len(chunks),
                    "chunks": self._chunk_details(chunks, include_content),
                    "embedding_usage": embedding_report,
                },
                run_type="retriever",
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
                await trace.step(
                    "02-rerank",
                    {"input_ranks": ranks, **reranker_config},
                    {
                        "input_ranks": ranks,
                        "output_ranks": ranks,
                        "ordered_chunks": self._chunk_details(chunks, include_content),
                        "reranker_config": reranker_config,
                        "note": "query_collection returned this final order. Distances are retrieval return values; Open WebUI does not expose a separate reranker score here.",
                    },
                )
                validated, validation = await self._validate(query, chunks)
            else:
                await trace.step(
                    "02-rerank",
                    {"input_ranks": [], "skipped": True},
                    {"output_ranks": [], "skipped": True, "reason": "No Knowledge Base chunks retrieved."},
                )
            await trace.step(
                "03-validate-kb",
                {"query": query, "chunks": self._chunk_details(chunks, include_content)},
                {"accepted": self._chunk_details(validated, include_content), "rejected_ranks": [c["rank"] for c in chunks if c not in validated], **validation},
                run_type="llm" if chunks else "chain",
                metadata=self._ls_model_metadata("google_genai", self._setting("VALIDATION_MODEL")) if chunks else None,
                usage_metadata=validation.get("usage_metadata"),
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
                        web_chunks, web_report = await self._web_search(__request__, query, web_user, include_content)
                        web_validation = web_report.get("validation", {})
                        await trace.step(
                            "04-web-search",
                            {"query": query, "engine": web_report.get("engine"), "queries": web_report.get("queries", [])},
                            {
                                "enabled": True,
                                "result_count": len(web_report.get("search_results", [])),
                                "search_results": web_report.get("search_results", []),
                                "errors": web_report.get("fetch_errors", []),
                            },
                        )
                        await trace.step(
                            "05-web-filter",
                            {"candidate_count": len(web_report.get("search_results", []))},
                            {
                                "prefilter_rejections": web_report.get("prefilter_rejections", []),
                                "fetched_candidates": web_report.get("fetched_candidates", []),
                            },
                        )
                        await trace.step(
                            "06-web-validate",
                            {"query": query, "candidate_count": len(web_report.get("fetched_candidates", []))},
                            {
                                "accepted": self._chunk_details(web_chunks, include_content),
                                "accepted_ranks": web_validation.get("decision", {}).get("accepted_ranks", []),
                                "rejected_ranks": web_validation.get("decision", {}).get("rejected_ranks", []),
                                **web_validation,
                            },
                            run_type="llm" if web_report.get("fetched_candidates") else "chain",
                            metadata=self._ls_model_metadata("google_genai", self._setting("VALIDATION_MODEL"))
                            if web_report.get("fetched_candidates")
                            else None,
                            usage_metadata=web_validation.get("usage_metadata"),
                        )
                    except Exception as exc:
                        web_report = {
                            "enabled": True,
                            "error": f"{type(exc).__name__}: {exc}",
                            "queries": self._web_queries(query),
                        }
                        await trace.step(
                            "04-web-search",
                            {"query": query, "queries": web_report["queries"]},
                            {"enabled": True, "result_count": 0, "errors": [web_report["error"]]},
                            error=type(exc).__name__,
                        )
                        await trace.step(
                            "05-web-filter",
                            {"candidate_count": 0},
                            {"prefilter_rejections": [], "fetched_candidates": [], "reason": "Web search failed."},
                            error=type(exc).__name__,
                        )
                        await trace.step(
                            "06-web-validate",
                            {"query": query, "candidate_count": 0},
                            {"accepted": [], "reason": "Web search failed; no external evidence accepted."},
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
                    f"Web search status: {'enabled but no validated IDS/Oracle result' if web_enabled else 'disabled by configuration'}.\n"
                    "</NO_RELEVANT_EVIDENCE>"
                )
                included_ranks = []
                citation_chunks = []
            sources = self._sources(citation_chunks)
            await trace.step(
                "07-build-context",
                {"evidence_origin": evidence_origin, "validated_ranks": [c["rank"] for c in evidence_chunks]},
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

            user = UserModel.model_validate(__user__) if isinstance(__user__, dict) else __user__
            nova_model = await Models.get_model_by_id(self._setting("NOVA_MODEL"))
            system_prompt = None
            if nova_model and nova_model.params:
                system_prompt = nova_model.params.model_dump().get("system")
            downstream_body = self._build_nova_body(body, context, evidence_origin)
            effective_body = await self._effective_nova_request(downstream_body, nova_model, user)
            await trace.step(
                "08-nova-input",
                {"model": self._setting("NOVA_MODEL"), "evidence_origin": evidence_origin, "context": context if include_content else "<content omitted>"},
                {
                    "dispatcher_request": downstream_body if include_content else {"model": downstream_body["model"], "stream": True, "message_count": len(downstream_body.get("messages", []))},
                    "effective_provider_request": effective_body if include_content else {"model": effective_body.get("model"), "stream": effective_body.get("stream"), "message_count": len(effective_body.get("messages", []))},
                    "configured_system_prompt": system_prompt or "<not found in model preset>",
                    "system_prompt_applied_by": "Open WebUI internal dispatcher",
                    "evidence_origin": evidence_origin,
                    "web_search_report": web_report,
                    "note": "dispatcher_request is sent to Open WebUI; effective_provider_request shows the model-preset system prompt and parameters applied on the way to Nova.",
                },
            )
            events, nova_output, nova_raw_usage = await self._nova(__request__, downstream_body, user)
            nova_provider_model = str(effective_body.get("model") or self._setting("NOVA_MODEL"))
            nova_usage_report = await self._nova_usage(
                nova_raw_usage,
                model=nova_provider_model,
            )
            await trace.step(
                "09-nova-output",
                {"model": nova_provider_model},
                {
                    "event_count": len(events),
                    "final_output": nova_output,
                    "raw_events": events if include_content else ["<events omitted>"],
                    **nova_usage_report,
                },
                run_type="llm",
                metadata=self._ls_model_metadata(str(self._setting("NOVA_PROVIDER") or "openwebui"), nova_provider_model),
                usage_metadata=nova_usage_report.get("usage_metadata"),
            )
            # The internal dispatcher returns provider SSE frames. Do not
            # forward those frames through the Pipe protocol: Open WebUI's
            # outer stream handler would parse and serialize them a second
            # time, which can introduce broken Markdown/word boundaries.
            # Emit one clean assistant payload instead.
            if nova_output:
                yield nova_output

            # Realtime chat handles citations as event-emitter events. A
            # top-level {"sources": [...]} object is ignored by the Pipe
            # middleware, so emit one source event per grouped file/source.
            for source in sources:
                yield {"event": {"type": "source", "data": source}}

            if nova_raw_usage:
                yield {"usage": nova_raw_usage}
            final_output = {
                "status": "success",
                "answer": nova_output,
                "sources": sources,
                "citation_count": len(sources),
                "evidence_origin": evidence_origin,
            }
            await trace.step("10-finalize", {"answer": nova_output}, final_output)
        except Exception as exc:
            final_output = {
                "status": "error",
                "error_type": type(exc).__name__,
                "error": str(exc),
            }
            await trace.step("error", {"query": query}, final_output, error=type(exc).__name__)
            yield f"The Knowledge Base Pipe could not complete this request: {type(exc).__name__}."
        finally:
            await trace.finish(final_output)
