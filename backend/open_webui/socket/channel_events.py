"""Pure helpers for persisting pipeline events on channel messages."""

from __future__ import annotations

from typing import Any


def _message_data(data: Any) -> dict[str, Any]:
    return dict(data) if isinstance(data, dict) else {}


def channel_event_patch(
    *,
    event_type: str,
    event_payload: Any,
    message_id: str,
    content: str,
    data: Any,
) -> dict[str, Any] | None:
    """Return the channel message fields changed by a pipeline UI event."""
    if not isinstance(event_payload, dict):
        return None

    updated_data = _message_data(data)

    if event_type == "status":
        status_history = list(updated_data.get("statusHistory") or [])
        status_history.append(dict(event_payload))
        updated_data["statusHistory"] = status_history
        return {"content": content, "data": updated_data}

    if event_type in {"source", "citation"}:
        if event_payload.get("type") is not None:
            return None

        sources = list(updated_data.get("sources") or [])
        sources.append(dict(event_payload))
        updated_data["sources"] = sources
        return {"content": content, "data": updated_data}

    if event_type == "chat:outlet":
        messages = event_payload.get("messages")
        if not isinstance(messages, list):
            return None

        message_patch = next(
            (
                item
                for item in messages
                if isinstance(item, dict) and item.get("id") == message_id
            ),
            None,
        )
        if message_patch is None or "sources" not in message_patch:
            return None

        sources = message_patch.get("sources")
        updated_data["sources"] = list(sources) if isinstance(sources, list) else []
        return {"content": content, "data": updated_data}

    return None
