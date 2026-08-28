"""Live corporate web-search evaluation for the Tara Ops V2 Pipe.

Run from the backend environment with the same database/API configuration as
the native OpenWebUI backend. The test forces the web-fallback branch so that
every case exercises web search even if the Knowledge Base has a matching item.
It prints classifications, timings, source metadata, and failure reasons, but
never prints environment variables or API keys.
"""

import asyncio
import os
import sys
from typing import Any


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)


QUESTIONS = [
    "Who is the CEO of RDC Concrete?",
    "Who is the CTO of RDC Concrete?",
    "Who is the Managing Director of RDC Concrete?",
    "Who founded RDC Concrete?",
    "When was RDC Concrete established?",
    "What is the company history of RDC Concrete?",
    "What is the official corporate website of RDC Concrete?",
    "Where is RDC Concrete headquartered?",
    "How many RMC plants does RDC Concrete operate?",
    "What are RDC Concrete's main business areas?",
    "Who leads RDC Concrete's operations?",
    "What departments does RDC Concrete have?",
    "What is RDC Concrete's corporate contact information?",
    "Who is part of RDC Concrete's leadership team?",
    "Is RDC Concrete a public or private company?",
]


async def run_case(pipe: Any, request: Any, user: Any, question: str) -> dict[str, Any]:
    from tools.test_pipe_matrix import TimedPipe

    result = await TimedPipe(pipe)._run(
        {"messages": [{"role": "user", "content": question}], "stream": True},
        user.model_dump(),
        request,
    )
    answer = str(result.get("answer", ""))
    source_details: list[dict[str, Any]] = []
    for event in result.get("events", []):
        if not isinstance(event, dict):
            continue
        source_event = event.get("event") or {}
        if source_event.get("type") != "source":
            continue
        data = source_event.get("data") or {}
        for metadata in data.get("metadata") or []:
            source_details.append(
                {
                    "name": metadata.get("name"),
                    "url": metadata.get("url") or metadata.get("link"),
                    "content_source": metadata.get("content_source", "page"),
                }
            )

    domain = result.get("domain") or {}
    stage_ms = result.get("stage_ms") or {}
    mistakes: list[str] = []
    if domain.get("decision") == "out_of_domain":
        mistakes.append("corporate_question_rejected_by_domain_gate")
    if "I can only assist with RDC Concrete" in answer:
        mistakes.append("nova_used_out_of_domain_refusal")
    if result.get("error"):
        mistakes.append("nova_or_pipe_error")
    if not answer.strip():
        mistakes.append("empty_answer")
    if not stage_ms.get("web_search"):
        mistakes.append("web_search_stage_not_executed")
    if any(source.get("content_source") == "page" and source.get("name") == "Just a moment..." for source in source_details):
        mistakes.append("challenge_page_returned_as_source")

    return {
        "question": question,
        "domain": domain.get("decision"),
        "domain_area": domain.get("domain_area"),
        "total_ms": result.get("total_ms"),
        "stage_ms": stage_ms,
        "source_count": result.get("source_count", 0),
        "sources": source_details,
        "answer_preview": " ".join(answer.split())[:240],
        "error": result.get("error", ""),
        "mistakes": mistakes,
    }


async def main() -> None:
    from starlette.requests import Request

    from open_webui.main import app
    from open_webui.models.models import Models
    from open_webui.models.users import Users
    from open_webui.utils.models import get_all_models
    from tools.main_pipe import Pipe

    os.environ["ENABLE_WEB_SEARCH"] = "true"
    os.environ["MIN_SOURCES"] = "999"

    users = await Users.get_users(limit=1)
    if not users["users"]:
        raise RuntimeError("No OpenWebUI user exists for the authenticated Pipe test")
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
    nova = await Models.get_model_by_id("nova")
    print(f"MODEL_PRESET_PRESENT={bool(nova)}")
    print(f"MODEL_PRESET_SYSTEM_PROMPT_PRESENT={bool(nova and nova.params and nova.params.model_dump().get('system'))}")
    print(f"CASE_COUNT={len(QUESTIONS)}")
    print("WEB_SEARCH_FORCED=true")

    results = []
    for question in QUESTIONS:
        result = await run_case(Pipe(), request, user, question)
        results.append(result)
        print("CASE=" + repr(result))

    passed = [result for result in results if not result["mistakes"]]
    total_values = [float(result["total_ms"] or 0) for result in results]
    web_values = [float(result["stage_ms"].get("web_search", 0)) for result in results]
    print(f"SUMMARY_PASS={len(passed)}")
    print(f"SUMMARY_FAIL={len(results) - len(passed)}")
    print(f"SUMMARY_AVG_TOTAL_MS={round(sum(total_values) / len(total_values), 1)}")
    print(f"SUMMARY_AVG_WEB_SEARCH_MS={round(sum(web_values) / len(web_values), 1)}")
    print(f"SUMMARY_MIN_TOTAL_MS={min(total_values)}")
    print(f"SUMMARY_MAX_TOTAL_MS={max(total_values)}")
    print("SUMMARY_FAILURES=" + repr([result for result in results if result["mistakes"]]))


if __name__ == "__main__":
    asyncio.run(main())
