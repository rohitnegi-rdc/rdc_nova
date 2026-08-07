"""Live evaluation matrix for the grounded Nova pipe.

Run from the backend environment with the same database/API configuration as the
native WSL backend. The report intentionally prints metrics and classifications,
not prompts, answers, API keys, or retrieved content.
"""

import asyncio
import os
import sys
import time
from typing import Any


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)


CASES = [
    {
        "id": "kb_exact_parallel_silos",
        "kind": "in_domain_kb_hit",
        "question": "Running Two BINs/SILOs Simultaneously (Coarse Feeding / Parallel Feed)",
    },
    {
        "id": "kb_mix_design_missing",
        "kind": "in_domain_kb_hit",
        "question": "A new mix design FG code is not appearing in IDS. What should I do?",
    },
    {
        "id": "kb_material_code",
        "kind": "in_domain_kb_hit",
        "question": "Please add FAMSAND code in IDS and assign its bin.",
    },
    {
        "id": "kb_mixer_fault",
        "kind": "in_domain_kb_hit",
        "question": "Mixer not ready fault aa rha hai, what do I check?",
    },
    {
        "id": "kb_admixture_fault",
        "kind": "in_domain_kb_hit",
        "question": "Admixture dosing is more than target.",
    },
    {
        "id": "kb_plc_fault",
        "kind": "in_domain_kb_hit",
        "question": "PLC is not getting connected in batching.",
    },
    {
        "id": "kb_event_viewer_paraphrase",
        "kind": "in_domain_kb_hit",
        "question": "Where do I investigate an unexpected batching error first?",
    },
    {
        "id": "domain_kb_miss_moisture",
        "kind": "in_domain_kb_miss",
        "question": "How should I adjust the concrete mix when aggregate moisture changes?",
    },
    {
        "id": "domain_kb_miss_dispatch",
        "kind": "in_domain_kb_miss",
        "question": "How can I optimize RMC truck dispatch scheduling during peak demand?",
    },
    {
        "id": "ambiguous_silo",
        "kind": "ambiguous_domain_term",
        "question": "How do I use a silo?",
    },
    {
        "id": "out_of_domain_politics",
        "kind": "out_of_domain",
        "question": "Who is the president of France?",
    },
    {
        "id": "out_of_domain_coding",
        "kind": "out_of_domain",
        "question": "Write a Python web scraper for me.",
    },
    {
        "id": "web_fallback_oracle",
        "kind": "in_domain_web_fallback",
        "question": "How can Oracle ERP supply chain order management integrate with IDS batching operations?",
        "enable_web": True,
    },
]


class TimedPipe:
    """Proxy that times the expensive pipe stages without changing production code."""

    def __init__(self, pipe: Any):
        self.pipe_impl = pipe
        self.stage_ms: dict[str, float] = {}
        self.domain_report: dict[str, Any] = {}

    async def _timed(self, name: str, method: Any, *args: Any, **kwargs: Any) -> Any:
        started = time.perf_counter()
        try:
            return await method(*args, **kwargs)
        finally:
            self.stage_ms[name] = round((time.perf_counter() - started) * 1000, 1)

    async def _run(self, body: dict[str, Any], user: dict[str, Any], request: Any):
        pipe = self.pipe_impl

        original_domain = pipe._domain_check

        async def timed_domain(*args: Any, **kwargs: Any) -> Any:
            result = await self._timed("domain_check", original_domain, *args, **kwargs)
            self.domain_report = result
            return result

        pipe._domain_check = timed_domain
        for name in ("_retrieve", "_validate", "_validate_web", "_nova", "_web_search"):
            original = getattr(pipe, name)

            async def timed_method(*args: Any, _name=name, _original=original, **kwargs: Any) -> Any:
                return await self._timed(_name.lstrip("_"), _original, *args, **kwargs)

            setattr(pipe, name, timed_method)

        started = time.perf_counter()
        events: list[Any] = []
        source_count = 0
        source_names: list[str] = []
        error = ""
        try:
            async for item in pipe.pipe(body=body, __user__=user, __request__=request):
                events.append(item)
                if isinstance(item, dict) and "sources" in item:
                    sources = item.get("sources") or []
                    source_count = len(sources)
                    source_names = [
                        str((source.get("source") or {}).get("name", ""))
                        for source in sources
                    ]
                elif isinstance(item, dict):
                    source_event = item.get("event") or {}
                    if source_event.get("type") == "source" and source_event.get("data"):
                        source = source_event["data"]
                        source_count += 1
                        source_names.append(str((source.get("source") or {}).get("name", "")))
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
        total_ms = round((time.perf_counter() - started) * 1000, 1)

        answer = ""
        for event in events:
            if isinstance(event, str):
                streamed = pipe._stream_text(event)
                answer += streamed if streamed else event

        return {
            "total_ms": total_ms,
            "stage_ms": dict(self.stage_ms),
            "domain": self.domain_report,
            "source_count": source_count,
            "source_names": source_names,
            "answer_length": len(answer),
            "has_kb_prefix": "Answering from Knowledge Base" in answer,
            "has_web_prefix": "Answering from Web Search" in answer,
            "has_out_of_domain_message": "I can only assist with RDC Concrete operations" in answer,
            "has_no_evidence_disclosure": any(
                phrase in answer.lower()
                for phrase in (
                    "no validated knowledge base",
                    "no validated evidence",
                    "could not find a solution",
                    "unable to find a solution",
                )
            ),
            "has_pipe_error": "could not complete this request" in answer,
            "error": error,
        }


def classify_result(case: dict[str, Any], result: dict[str, Any]) -> list[str]:
    mistakes: list[str] = []
    domain = result.get("domain") or {}
    decision = domain.get("decision")
    kind = case["kind"]

    if kind == "out_of_domain" and not result["has_out_of_domain_message"]:
        mistakes.append("out_of_domain_not_bypassed")
    if kind in {"in_domain_kb_hit", "in_domain_kb_miss", "in_domain_web_fallback"} and decision == "out_of_domain":
        mistakes.append("in_domain_rejected_by_domain_gate")
    if kind == "ambiguous_domain_term" and decision == "out_of_domain":
        mistakes.append("ambiguous_term_rejected")
    if kind == "in_domain_kb_hit" and result["source_count"] == 0:
        mistakes.append("expected_kb_source_missing")
    if kind == "in_domain_kb_hit" and not result["has_kb_prefix"]:
        mistakes.append("missing_kb_answer_label")
    if kind in {"in_domain_kb_miss", "in_domain_web_fallback"} and result["source_count"] == 0 and not result["has_no_evidence_disclosure"]:
        mistakes.append("missing_no_evidence_disclosure")
    if kind == "in_domain_web_fallback" and not result["has_web_prefix"] and result["source_count"] > 0:
        mistakes.append("web_source_not_labeled")
    if result["has_pipe_error"] or result["error"]:
        mistakes.append("pipe_error")
    return mistakes


async def main() -> None:
    from starlette.requests import Request

    from open_webui.main import app
    from open_webui.models.models import Models
    from open_webui.models.users import Users
    from open_webui.utils.models import get_all_models
    from tools.main_pipe import Pipe

    users = await Users.get_users(limit=1)
    if not users["users"]:
        raise RuntimeError("No Open WebUI user exists for the authenticated pipe test")
    user = users["users"][0]
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/chat/completions",
            "headers": [],
            "query_string": b"",
            "client": ("127.0.0.1", 0),
            "scheme": "http",
            "server": ("localhost", 8080),
            "root_path": "",
            "http_version": "1.1",
            "app": app,
        },
    )
    await get_all_models(request, user=user)
    nova_model = await Models.get_model_by_id("nova")
    nova_system_prompt = bool(
        nova_model
        and nova_model.params
        and nova_model.params.model_dump().get("system")
    )
    print(f"MODEL_PRESET_PRESENT={bool(nova_model)}")
    print(f"MODEL_PRESET_SYSTEM_PROMPT_PRESENT={nova_system_prompt}")
    print(f"MODEL_REGISTRY_COUNT={len(app.state.MODELS)}")

    selected_ids = {
        item.strip()
        for item in os.getenv("PIPE_MATRIX_IDS", "").split(",")
        if item.strip()
    }
    cases = [case for case in CASES if not selected_ids or case["id"] in selected_ids]
    results: list[dict[str, Any]] = []
    for case in cases:
        os.environ["ENABLE_WEB_SEARCH"] = "true" if case.get("enable_web") else "false"
        pipe = TimedPipe(Pipe())
        result = await pipe._run(
            {"messages": [{"role": "user", "content": case["question"]}], "stream": True},
            user.model_dump(),
            request,
        )
        mistakes = classify_result(case, result)
        result = {
            "id": case["id"],
            "kind": case["kind"],
            "question": case["question"],
            "enable_web": bool(case.get("enable_web")),
            **result,
            "mistakes": mistakes,
        }
        results.append(result)
        print(
            "CASE "
            + case["id"]
            + f" total_ms={result['total_ms']} source_count={result['source_count']} "
            + f"domain={result['domain'].get('decision', 'missing')} "
            + f"domain_conf={result['domain'].get('confidence', 0)} "
            + f"kb_label={result['has_kb_prefix']} web_label={result['has_web_prefix']} "
            + f"no_evidence={result['has_no_evidence_disclosure']} "
            + f"sources={result['source_names']} stages={result['stage_ms']} mistakes={mistakes or 'none'}"
        )

    successful = [row for row in results if not row["mistakes"]]
    total_values = [row["total_ms"] for row in results]
    successful_values = [row["total_ms"] for row in successful]
    print(f"SUMMARY_CASE_COUNT={len(results)}")
    print(f"SUMMARY_SUCCESS_COUNT={len(successful)}")
    print(f"SUMMARY_FAILURE_COUNT={len(results) - len(successful)}")
    print(f"SUMMARY_AVG_TOTAL_MS={round(sum(total_values) / len(total_values), 1)}")
    print(f"SUMMARY_AVG_SUCCESS_MS={round(sum(successful_values) / len(successful_values), 1) if successful_values else 0}")
    print(f"SUMMARY_MIN_TOTAL_MS={min(total_values)}")
    print(f"SUMMARY_MAX_TOTAL_MS={max(total_values)}")
    for stage in ("domain_check", "retrieve", "validate", "validate_web", "web_search", "nova"):
        values = [row["stage_ms"][stage] for row in results if stage in row["stage_ms"]]
        if values:
            print(f"SUMMARY_AVG_{stage.upper()}_MS={round(sum(values) / len(values), 1)}")
    mistakes = sorted({mistake for row in results for mistake in row["mistakes"]})
    print(f"SUMMARY_MISTAKE_TYPES={mistakes or 'none'}")


if __name__ == "__main__":
    asyncio.run(main())
