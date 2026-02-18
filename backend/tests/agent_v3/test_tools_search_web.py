import asyncio
import json
import unittest
from unittest.mock import patch

from ts_pit.agent_v3 import tools


class SearchWebToolTests(unittest.TestCase):
    def test_no_results_exception_is_returned_as_ok_empty_payload(self):
        with patch.object(tools, "_extract_candidate_tickers", return_value=[]), patch.object(
            tools, "_lookup_instrument_names_for_tickers", return_value={}
        ), patch.object(tools, "_refine_search_query_with_llm", return_value=None), patch.object(
            tools, "_run_ddgs_search", side_effect=Exception("No results found.")
        ):
            raw = asyncio.run(
                tools.search_web.ainvoke(
                    {
                        "query": "HEMO.L news",
                        "max_results": 5,
                        "start_date": "2025-08-15",
                        "end_date": "2025-08-29",
                    }
                )
            )

        parsed = json.loads(raw)
        self.assertTrue(parsed.get("ok"))
        self.assertEqual(parsed.get("error"), None)
        data = parsed.get("data") or {}
        self.assertEqual(data.get("combined"), [])
        self.assertEqual(data.get("web"), [])
        self.assertEqual(data.get("news"), [])


if __name__ == "__main__":
    unittest.main()
