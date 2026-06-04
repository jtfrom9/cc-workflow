#!/usr/bin/env python3
"""Unit tests for the pure logic in ``tools/session_usage.py``.

Network, token retrieval, and cache I/O are side-effecting and are not
exercised here; only the deterministic parsing/formatting helpers are.

Run from the repo root::

    python3 -m unittest discover -s tests
"""

from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import session_usage as su  # noqa: E402


class ExtractTokenTests(unittest.TestCase):
    def test_reads_nested_access_token(self):
        blob = '{"claudeAiOauth": {"accessToken": "sk-tok-123", "refreshToken": "r"}}'
        self.assertEqual(su.extract_token_from_blob(blob), "sk-tok-123")

    def test_missing_key_returns_none(self):
        self.assertIsNone(su.extract_token_from_blob('{"claudeAiOauth": {}}'))
        self.assertIsNone(su.extract_token_from_blob('{"other": 1}'))

    def test_invalid_json_returns_none(self):
        self.assertIsNone(su.extract_token_from_blob("not json"))
        self.assertIsNone(su.extract_token_from_blob(""))


class ParseUsageTests(unittest.TestCase):
    def test_remaining_is_complement_of_utilization(self):
        data = {
            "five_hour": {"utilization": 15.0, "resets_at": "2026-06-04T06:20:00+00:00"},
            "seven_day": {"utilization": 4.0, "resets_at": "2026-06-09T16:00:00+00:00"},
        }
        out = su.parse_usage(data)
        self.assertAlmostEqual(out["five_hour"]["remaining_pct"], 85.0)
        self.assertEqual(out["five_hour"]["resets_at"], "2026-06-04T06:20:00+00:00")
        self.assertAlmostEqual(out["seven_day"]["remaining_pct"], 96.0)

    def test_missing_or_null_windows_are_none(self):
        out = su.parse_usage({"seven_day_opus": None})
        self.assertIsNone(out["five_hour"])
        self.assertIsNone(out["seven_day"])

    def test_null_utilization_is_none(self):
        out = su.parse_usage({"five_hour": {"utilization": None, "resets_at": None}})
        self.assertIsNone(out["five_hour"])

    def test_over_full_clamps_to_zero(self):
        out = su.parse_usage({"five_hour": {"utilization": 130.0, "resets_at": None}})
        self.assertEqual(out["five_hour"]["remaining_pct"], 0.0)


class FormatTimeLeftTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 6, 4, 4, 0, 0, tzinfo=timezone.utc)

    def test_hours_and_minutes(self):
        self.assertEqual(
            su.format_time_left("2026-06-04T06:21:00+00:00", self.now), "2h21m"
        )

    def test_minutes_only(self):
        self.assertEqual(
            su.format_time_left("2026-06-04T04:21:00+00:00", self.now), "21m"
        )

    def test_under_a_minute(self):
        self.assertEqual(
            su.format_time_left("2026-06-04T04:00:30+00:00", self.now), "<1m"
        )

    def test_past_or_none_is_empty(self):
        self.assertEqual(su.format_time_left("2026-06-04T03:00:00+00:00", self.now), "")
        self.assertEqual(su.format_time_left(None, self.now), "")
        self.assertEqual(su.format_time_left("", self.now), "")


class EmojiTests(unittest.TestCase):
    def test_thresholds(self):
        self.assertEqual(su.session_emoji(85), "🟢")
        self.assertEqual(su.session_emoji(50), "🟡")
        self.assertEqual(su.session_emoji(20), "🟠")
        self.assertEqual(su.session_emoji(5), "🔴")
        self.assertEqual(su.session_emoji(0), "🔴")


class RenderSegmentTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 6, 4, 4, 0, 0, tzinfo=timezone.utc)

    def test_full_segment(self):
        usage = {
            "five_hour": {"remaining_pct": 85.0, "resets_at": "2026-06-04T06:21:00+00:00"},
            "seven_day": {"remaining_pct": 96.0, "resets_at": "2026-06-09T16:00:00+00:00"},
        }
        self.assertEqual(su.render_segment(usage, self.now), "🟢 85% 2h21m · 7d 96%")

    def test_omits_time_when_unknown(self):
        usage = {
            "five_hour": {"remaining_pct": 40.0, "resets_at": None},
            "seven_day": None,
        }
        self.assertEqual(su.render_segment(usage, self.now), "🟡 40%")

    def test_empty_when_no_five_hour(self):
        self.assertEqual(su.render_segment({"five_hour": None, "seven_day": None}, self.now), "")


if __name__ == "__main__":
    unittest.main()
