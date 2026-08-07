"""Offline tests for the grounded pipe's token and cost accounting."""

import asyncio
from types import SimpleNamespace
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from tools.main_pipe import Pipe


def main() -> None:
    pipe = Pipe()
    response = SimpleNamespace(
        usage_metadata=SimpleNamespace(
            prompt_token_count=1000,
            candidates_token_count=200,
            thoughts_token_count=50,
            total_token_count=1250,
        )
    )
    report = pipe._gemini_usage(
        response,
        model="gemini-3.5-flash-lite",
    )
    assert report["usage_status"] == "provider_reported"
    assert report["usage_metadata"]["input_tokens"] == 1000
    assert report["usage_metadata"]["output_tokens"] == 250
    assert report["usage_metadata"]["total_tokens"] == 1250
    assert "cost" not in report

    stream = "data: {\"choices\":[],\"usage\":{\"prompt_tokens\":1200,\"completion_tokens\":300,\"total_tokens\":1500}}\n\n"
    assert pipe._stream_usage(stream) == {
        "input_tokens": 1200,
        "output_tokens": 300,
        "total_tokens": 1500,
    }

    nova_report = asyncio.run(
        pipe._nova_usage(
            {"input_tokens": 2000, "output_tokens": 400, "total_tokens": 2400},
            model="models/gemini-3.1-flash-lite",
        )
    )
    assert nova_report["usage_status"] == "provider_reported"
    assert nova_report["usage_metadata"]["input_tokens"] == 2000
    assert nova_report["usage_metadata"]["output_tokens"] == 400
    assert nova_report["usage_metadata"]["total_tokens"] == 2400
    assert "cost" not in nova_report

    print("COST_ACCOUNTING_TEST=PASS")
    print("COST_SOURCE=provider_reported_usage_only")


if __name__ == "__main__":
    main()
