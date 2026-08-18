"""Contract tests for adapting pipeline events to persisted channel message data."""

import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "backend"
    / "open_webui"
    / "socket"
    / "channel_events.py"
)


def _load_channel_events_module():
    spec = importlib.util.spec_from_file_location("channel_events", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ChannelMessageEventTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.events = _load_channel_events_module()

    def test_status_is_appended_without_losing_existing_message_data(self):
        existing = {
            "files": [{"id": "file-1"}],
            "statusHistory": [{"action": "query", "description": "Understanding query"}],
        }

        patch = self.events.channel_event_patch(
            event_type="status",
            event_payload={"action": "search", "description": "Searching knowledge base"},
            message_id="message-1",
            content="",
            data=existing,
        )

        self.assertEqual(patch["content"], "")
        self.assertEqual(patch["data"]["files"], [{"id": "file-1"}])
        self.assertEqual(
            [status["action"] for status in patch["data"]["statusHistory"]],
            ["query", "search"],
        )
        self.assertEqual(existing["statusHistory"], [{"action": "query", "description": "Understanding query"}])

    def test_source_and_citation_events_are_appended(self):
        source = {
            "source": {"id": "kb-1", "name": "IDS guide"},
            "document": ["Parallel feeding evidence"],
        }

        for event_type in ("source", "citation"):
            with self.subTest(event_type=event_type):
                patch = self.events.channel_event_patch(
                    event_type=event_type,
                    event_payload=source,
                    message_id="message-1",
                    content="Answer [1]",
                    data={"statusHistory": [{"action": "answer"}]},
                )

                self.assertEqual(patch["data"]["sources"], [source])
                self.assertEqual(patch["data"]["statusHistory"], [{"action": "answer"}])

    def test_chat_outlet_replaces_native_sources_with_pipe_sources(self):
        pipe_sources = [
            {
                "source": {"id": "kb-2", "name": "Validated guide"},
                "document": ["Validated evidence"],
            }
        ]

        patch = self.events.channel_event_patch(
            event_type="chat:outlet",
            event_payload={
                "messages": [
                    {"id": "another-message", "sources": [{"source": {"id": "wrong"}}]},
                    {"id": "message-1", "sources": pipe_sources},
                ]
            },
            message_id="message-1",
            content="Grounded answer [1]",
            data={
                "sources": [{"source": {"id": "native-source"}}],
                "statusHistory": [{"action": "done", "done": True}],
            },
        )

        self.assertEqual(patch["data"]["sources"], pipe_sources)
        self.assertEqual(patch["data"]["statusHistory"], [{"action": "done", "done": True}])

    def test_irrelevant_or_typed_source_events_do_not_modify_message(self):
        self.assertIsNone(
            self.events.channel_event_patch(
                event_type="source",
                event_payload={"type": "tool", "name": "not-a-citation"},
                message_id="message-1",
                content="",
                data={},
            )
        )
        self.assertIsNone(
            self.events.channel_event_patch(
                event_type="chat:outlet",
                event_payload={"messages": [{"id": "another-message", "sources": []}]},
                message_id="message-1",
                content="",
                data={},
            )
        )


if __name__ == "__main__":
    unittest.main()
