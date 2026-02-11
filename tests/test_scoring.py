import unittest

from backend.scoring import calculate_p2


class TestCalculateP2(unittest.TestCase):
    def test_datetime_with_space_and_timezone_scores_high_when_close_to_end(self):
        score = calculate_p2("2025-08-28 00:39:05+00:00", "2025-08-15", "2025-08-29")
        self.assertEqual(score, "H")

    def test_datetime_with_space_scores_high_when_close_to_end(self):
        score = calculate_p2("2025-08-28 00:00:00", "2025-08-15", "2025-08-29")
        self.assertEqual(score, "H")

    def test_invalid_article_date_defaults_low(self):
        score = calculate_p2("not-a-date", "2025-08-15", "2025-08-29")
        self.assertEqual(score, "L")


if __name__ == "__main__":
    unittest.main()
