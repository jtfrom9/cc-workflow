#!/usr/bin/env python3
"""Unit tests for the pure logic in ``tools/status_line.py``.

Run from the repo root::

    python3 -m unittest discover -s tests
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import status_line as sl  # noqa: E402


class CostSegmentTests(unittest.TestCase):
    def test_missing_cost_returns_empty(self):
        self.assertEqual(sl._cost_segment({}), "")

    def test_cost_not_a_dict_returns_empty(self):
        self.assertEqual(sl._cost_segment({"cost": "oops"}), "")

    def test_missing_total_cost_usd_returns_empty(self):
        self.assertEqual(sl._cost_segment({"cost": {}}), "")

    def test_zero_cost_returns_empty(self):
        self.assertEqual(sl._cost_segment({"cost": {"total_cost_usd": 0}}), "")

    def test_renders_dollar_amount(self):
        self.assertEqual(
            sl._cost_segment({"cost": {"total_cost_usd": 1.2345}}), "💰$1.23"
        )

    def test_small_amount_rounds_up(self):
        self.assertEqual(
            sl._cost_segment({"cost": {"total_cost_usd": 0.006}}), "💰$0.01"
        )


NOW = 1_800_000_000.0


class ContextSegmentTests(unittest.TestCase):
    def test_renders_from_context_window(self):
        payload = {"context_window": {
            "total_input_tokens": 562_000, "context_window_size": 1_000_000,
            "used_percentage": 56.2,
        }}
        self.assertEqual(sl._context_segment(payload), "🧠 ██████░░░░ 562k/1M (56%)")

    def test_null_percentage_renders_placeholder(self):
        payload = {"context_window": {"context_window_size": 200_000, "used_percentage": None}}
        self.assertEqual(sl._context_segment(payload), "🧠 —")

    def test_missing_context_window_renders_placeholder(self):
        self.assertEqual(sl._context_segment({}), "🧠 —")


class ModelLabelTests(unittest.TestCase):
    def test_strips_bracket_suffix(self):
        self.assertEqual(sl._model_label({"model": {"id": "claude-opus-5-5[1m]"}}), "claude-opus-5-5")

    def test_unknown_model(self):
        self.assertEqual(sl._model_label({}), "?")


class FormatTimeLeftTests(unittest.TestCase):
    def test_hours_and_minutes(self):
        self.assertEqual(sl._format_time_left(NOW + 2 * 3600 + 21 * 60 + 5, NOW), "2h21m")

    def test_minutes_only(self):
        self.assertEqual(sl._format_time_left(NOW + 21 * 60, NOW), "21m")

    def test_under_a_minute(self):
        self.assertEqual(sl._format_time_left(NOW + 30, NOW), "<1m")

    def test_past_or_none_is_empty(self):
        self.assertEqual(sl._format_time_left(NOW - 1, NOW), "")
        self.assertEqual(sl._format_time_left(None, NOW), "")


class LimitEmojiTests(unittest.TestCase):
    def test_thresholds(self):
        self.assertEqual(sl._limit_emoji(85), "🟢")
        self.assertEqual(sl._limit_emoji(50), "🟡")
        self.assertEqual(sl._limit_emoji(20), "🟠")
        self.assertEqual(sl._limit_emoji(5), "🔴")


class RateLimitSegmentTests(unittest.TestCase):
    def test_full_segment(self):
        payload = {"rate_limits": {
            "five_hour": {"used_percentage": 15, "resets_at": NOW + 2 * 3600 + 21 * 60},
            "seven_day": {"used_percentage": 4, "resets_at": NOW + 86400},
        }}
        self.assertEqual(sl._rate_limit_segment(payload, NOW), "🟢 85% 2h21m · 7d 96%")

    def test_omits_time_when_unknown(self):
        payload = {"rate_limits": {"five_hour": {"used_percentage": 15}}}
        self.assertEqual(sl._rate_limit_segment(payload, NOW), "🟢 85%")

    def test_seven_day_only(self):
        payload = {"rate_limits": {"seven_day": {"used_percentage": 40}}}
        self.assertEqual(sl._rate_limit_segment(payload, NOW), "7d 60%")

    def test_absent_for_non_subscribers(self):
        self.assertEqual(sl._rate_limit_segment({}, NOW), "")


class RenderTests(unittest.TestCase):
    def test_full_line(self):
        payload = {
            "workspace": {"current_dir": "/work/cc-workflow"},
            "model": {"id": "claude-opus-5-5"},
            "context_window": {
                "total_input_tokens": 562_000, "context_window_size": 1_000_000,
                "used_percentage": 56,
            },
            "cost": {"total_cost_usd": 1.23},
            "rate_limits": {"five_hour": {"used_percentage": 15}},
        }
        self.assertEqual(
            sl.render(payload, NOW),
            "📁 cc-workflow · 🧠 ██████░░░░ 562k/1M (56%) · claude-opus-5-5 · 💰$1.23 · 🟢 85%",
        )

    def test_empty_payload(self):
        self.assertEqual(sl.render({}, NOW), "🧠 — · ?")


if __name__ == "__main__":
    unittest.main()
