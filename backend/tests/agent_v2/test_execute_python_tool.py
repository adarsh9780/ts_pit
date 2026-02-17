import importlib
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch


class ExecutePythonToolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import ts_pit.agent_v2.tools as tools_module
        except ImportError:
            import sys
            from pathlib import Path

            sys.path.append(str(Path(__file__).parent.parent.parent / "src"))
            import ts_pit.agent_v2.tools as tools_module

        cls.tools = importlib.reload(tools_module)

    def _invoke_execute_python(self, code: str, input_data_json: str) -> dict:
        raw = self.tools.execute_python.invoke(
            {"code": code, "input_data_json": input_data_json}
        )
        return json.loads(raw)

    def test_execute_python_accepts_top_level_list_input(self):
        fake_result = SimpleNamespace(
            ok=True,
            result={"ok": True},
            stdout="",
            stderr="",
            timed_out=False,
            resource_exceeded=False,
            exit_code=0,
            error=None,
        )

        with (
            patch.object(
                self.tools, "ensure_python_runtime", return_value="/usr/bin/python3"
            ),
            patch.object(
                self.tools, "run_code", return_value=fake_result
            ) as run_code_mock,
        ):
            payload = self._invoke_execute_python(
                code="result = {'rows': len(input_rows)}",
                input_data_json='[{"x": 1}, {"x": 2}]',
            )

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["meta"].get("normalized_input_from"), "list")

        kwargs = run_code_mock.call_args.kwargs
        self.assertEqual(kwargs["input_data"], {"rows": [{"x": 1}, {"x": 2}]})


if __name__ == "__main__":
    unittest.main()
