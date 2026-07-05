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


if __name__ == "__main__":
    unittest.main()
