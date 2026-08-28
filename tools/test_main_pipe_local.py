"""Local smoke test for tools/main_pipe.py; run from the backend venv."""

import asyncio
import os
import sys
from starlette.requests import Request

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

QUESTION = os.getenv(
    "PIPE_TEST_QUESTION",
    "Running Two BINs/SILOs Simultaneously (Coarse Feeding / Parallel Feed)",
)


async def main() -> None:
    from open_webui.main import app
    from open_webui.models.users import Users
    from open_webui.utils.models import get_all_models
    from tools.main_pipe import Pipe

    pipe = Pipe()
    print("nova_model_present=" + str("nova" in app.state.MODELS))
    print("model_count=" + str(len(app.state.MODELS)))
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
    users = await Users.get_users(limit=1)
    if not users["users"]:
        raise RuntimeError("No Open WebUI user exists for the authenticated Tara Ops dispatch test")
    user = users["users"][0]
    await get_all_models(request, user=user)
    body = {"messages": [{"role": "user", "content": QUESTION}], "stream": True}
    results = []
    async for item in pipe.pipe(body=body, __user__=user.model_dump(), __request__=request):
        results.append(item)

    sources = []
    for item in results:
        if not isinstance(item, dict):
            continue
        if item.get("sources"):
            sources.extend(item["sources"])
        event = item.get("event") or {}
        if event.get("type") == "source" and event.get("data"):
            sources.append(event["data"])
    answer = "".join(item for item in results if isinstance(item, str))
    print(f"question={QUESTION}")
    print(f"source_count={len(sources)}")
    for source in sources:
        info = source.get("source", {})
        print(f"source_id={info.get('id')} source_name={info.get('name')}")
    print(f"has_citation_marker={'[' in answer and ']' in answer}")
    print("answer_start=" + answer[:1000].replace("\n", " "))


if __name__ == "__main__":
    asyncio.run(main())
