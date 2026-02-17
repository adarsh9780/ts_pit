import unittest

from unittest.mock import patch
from ts_pit.services.alert_normalizer import normalize_alert_response
from ts_pit import config as app_config


class AlertNormalizerTests(unittest.TestCase):
    def test_normalize_id_trade_type_and_dates(self):
        payload = {
            "alert_id": 123,
            "status": None,
            "buy_quantity": 200,
            "sell_quantity": 10,
            "start_date": "2026-02-01T00:00:00Z",
            "end_date": "2026-02-10",
            "execution_date": "2026-02-10T09:30:00Z",
        }

        with patch.object(app_config, "config", autospec=True):
            out = normalize_alert_response(payload)
        self.assertEqual(out["id"], "123")
        self.assertEqual(out["trade_type"], "BUY")
        self.assertEqual(out["start_date"], "2026-02-01")
        self.assertEqual(out["end_date"], "2026-02-10")
        self.assertEqual(out["execution_date"], "2026-02-10")


if __name__ == "__main__":
    unittest.main()
