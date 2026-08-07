"""Verify the latest grounded-knowledge-pipe trace without printing content."""

import os

from langsmith import Client


def main() -> None:
    project = os.getenv("LANGCHAIN_PROJECT", "open-webui-knowledge-pipe")
    client = Client()
    runs = list(client.list_runs(project_name=project, limit=100))
    roots = [run for run in runs if run.name == "grounded-knowledge-pipe"]
    root = max(roots, key=lambda run: run.start_time) if roots else None
    children = [run for run in runs if root and str(run.parent_run_id) == str(root.id)]
    by_name = {run.name: run for run in children}
    retrieve_output = (by_name.get("01-retrieve").outputs or {}) if by_name.get("01-retrieve") else {}
    validate_output = (by_name.get("03-validate-kb").outputs or {}) if by_name.get("03-validate-kb") else {}
    web_search_output = (by_name.get("04-web-search").outputs or {}) if by_name.get("04-web-search") else {}
    web_filter_output = (by_name.get("05-web-filter").outputs or {}) if by_name.get("05-web-filter") else {}
    web_validate_output = (by_name.get("06-web-validate").outputs or {}) if by_name.get("06-web-validate") else {}
    nova_input = (by_name.get("08-nova-input").outputs or {}) if by_name.get("08-nova-input") else {}
    nova_output = (by_name.get("09-nova-output").outputs or {}) if by_name.get("09-nova-output") else {}
    finalize_output = (by_name.get("10-finalize").outputs or {}) if by_name.get("10-finalize") else {}
    cost_summary = (root.outputs or {}).get("cost_summary", {}) if root else {}
    dispatcher_request = nova_input.get("dispatcher_request") or {}
    effective_request = nova_input.get("effective_provider_request") or {}
    dispatcher_messages = dispatcher_request.get("messages") or []
    effective_messages = effective_request.get("messages") or []

    print(f"langsmith_runs={len(runs)}")
    print(f"root_found={bool(root)}")
    print(f"root_id={root.id if root else ''}")
    print(f"root_output_keys={sorted((root.outputs or {}).keys()) if root else []}")
    print(f"root_has_answer={bool((root.outputs or {}).get('answer')) if root else False}")
    print(f"root_answer_length={len((root.outputs or {}).get('answer', '')) if root else 0}")
    print(f"cost_status={cost_summary.get('cost_status', '')}")
    print(f"total_cost_usd={cost_summary.get('total_cost_usd', '')}")
    print(f"total_input_tokens={cost_summary.get('input_tokens', '')}")
    print(f"total_output_tokens={cost_summary.get('output_tokens', '')}")
    print(f"cost_record_count={cost_summary.get('record_count', '')}")
    for index, record in enumerate(cost_summary.get("records") or [], 1):
        print(
            f"cost_record_{index}="
            f"name={record.get('name','')} model={record.get('model','')} "
            f"input_tokens={record.get('input_tokens',0)} output_tokens={record.get('output_tokens',0)} "
            f"total_cost_usd={record.get('total_cost_usd','')} status={record.get('cost_status','')}"
        )
    print(f"child_names={sorted(run.name for run in children)}")
    print(
        "child_output_keys="
        + str({run.name: sorted((run.outputs or {}).keys()) for run in children})
    )
    print(f"retrieved_chunk_count={retrieve_output.get('chunk_count', 0)}")
    print(f"validation_decision_present={bool(validate_output.get('decision'))}")
    decision = validate_output.get("decision") or {}
    print(f"validation_accepted_ranks={decision.get('accepted_ranks', [])}")
    print(f"validation_rejected_ranks={decision.get('rejected_ranks', [])}")
    print(f"root_status={(root.outputs or {}).get('status') if root else ''}")
    print(f"dispatcher_message_count={len(dispatcher_messages)}")
    print(f"dispatcher_model={dispatcher_request.get('model', '')}")
    print(f"effective_provider_model={effective_request.get('model', '')}")
    print(
        "dispatcher_contains_evidence="
        + str(any("Grounded evidence context:" in str(message.get("content", "")) for message in dispatcher_messages))
    )
    print(f"effective_request_has_system_prompt={any(message.get('role') == 'system' for message in effective_messages)}")
    print(f"nova_output_length={len(nova_output.get('final_output', ''))}")
    print(f"nova_cost={((nova_output.get('cost') or {}).get('total_cost_usd', ''))}")
    print(f"nova_usage_source={((nova_output.get('cost') or {}).get('usage_source', ''))}")
    print(f"embedding_usage={retrieve_output.get('embedding_usage', {})}")
    print(f"finalize_has_sources={bool(finalize_output.get('sources'))}")
    print(f"web_search_step_present={bool(web_search_output)}")
    print(f"web_filter_step_present={bool(web_filter_output)}")
    print(f"web_validate_step_present={bool(web_validate_output)}")
    print(f"web_accepted_count={len(web_validate_output.get('accepted', []))}")


if __name__ == "__main__":
    main()
