import unittest

from ts_pit.agent_v3.graph import master
from ts_pit.agent_v3.state import AgentV3State, StepState


class MasterExecutionRoutingTests(unittest.TestCase):
    def test_continues_with_pending_step_even_when_prior_step_failed(self):
        state = AgentV3State(
            last_user_question=None,
            plan_requires_execution=True,
            steps=[
                StepState(id="s1", instruction="step 1", status="done"),
                StepState(id="s2", instruction="step 2", status="done"),
                StepState(id="s3", instruction="step 3", status="failed", error="web failed"),
                StepState(id="s4", instruction="step 4", status="pending"),
            ],
            replan_attempts=1,
        )

        out = master(state, config={})

        self.assertEqual(out.get("next_step"), "execute")
        self.assertEqual(out.get("current_step_index"), 3)
        self.assertEqual(out.get("failed_step_index"), 2)

    def test_returns_failure_response_after_pending_steps_are_exhausted(self):
        state = AgentV3State(
            last_user_question=None,
            plan_requires_execution=True,
            steps=[
                StepState(id="s1", instruction="step 1", status="done"),
                StepState(id="s2", instruction="step 2", status="failed", error="tool failed"),
            ],
            replan_attempts=1,
        )

        out = master(state, config={})

        self.assertEqual(out.get("next_step"), "respond")
        self.assertEqual(out.get("failed_step_index"), 1)
        self.assertIn("tool failed", str(out.get("terminal_error")))


if __name__ == "__main__":
    unittest.main()
