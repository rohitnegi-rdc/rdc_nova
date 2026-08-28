"""Structural contract for Tara Ops V2's pipe orchestration."""

import ast
import inspect
import textwrap
import unittest

from tools import main_pipe


class PipeOrchestrationTests(unittest.TestCase):
    DIRECT_PIPE_HELPERS = (
        "_handle_task",
        "_start_trace",
        "_run_domain_check",
        "_handle_domain_result",
        "_gather_evidence",
        "_build_evidence_context",
        "_generate_nova_answer",
        "_finalize_response",
        "_handle_pipe_error",
    )
    EVIDENCE_HELPERS = (
        "_retrieve_and_validate_kb",
        "_maybe_search_web",
        "_select_evidence",
    )

    def test_pipe_is_a_small_orchestrator_over_named_helpers(self):
        self.assertTrue(inspect.isasyncgenfunction(main_pipe.Pipe.pipe))

        source = textwrap.dedent(inspect.getsource(main_pipe.Pipe.pipe))
        function = ast.parse(source).body[0]
        delegated_calls = {
            node.func.attr
            for node in ast.walk(function)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "self"
        }

        for helper_name in self.DIRECT_PIPE_HELPERS:
            with self.subTest(helper=helper_name):
                self.assertTrue(callable(getattr(main_pipe.Pipe, helper_name, None)))
                self.assertIn(helper_name, delegated_calls)

    def test_evidence_and_nova_work_are_split_into_focused_helpers(self):
        for helper_name in (*self.EVIDENCE_HELPERS, "_prepare_nova"):
            with self.subTest(helper=helper_name):
                self.assertTrue(callable(getattr(main_pipe.Pipe, helper_name, None)))


if __name__ == "__main__":
    unittest.main()
