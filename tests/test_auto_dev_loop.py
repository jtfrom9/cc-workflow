#!/usr/bin/env python3
"""Unit tests for the pure logic in ``tools/auto_dev_loop.py``.

Two deterministic concerns are exercised here: the scheduling logic
(dependency gating + concurrency budgeting) and the body<->state transform
(rendering the tracking-issue description and parsing it back). The ``gh``
calls that read/write the GitHub issue are side-effecting and are driven by
the skill itself.

Run from the repo root::

    python3 -m unittest discover -s tests
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import auto_dev_loop as adl  # noqa: E402


def _issue(number, status, deps=None):
    return {"number": number, "status": status, "deps": deps or []}


class ComputeReadyTests(unittest.TestCase):
    def test_analyzed_issue_with_no_deps_is_ready(self):
        issues = {"1": _issue(1, "analyzed")}
        result = adl.compute_ready(issues, concurrency=3)
        self.assertEqual(result["ready"], [1])
        self.assertEqual(result["in_flight"], 0)
        self.assertEqual(result["capacity"], 3)

    def test_dep_must_be_merged_before_dependent_is_ready(self):
        issues = {
            "1": _issue(1, "implementing"),
            "2": _issue(2, "analyzed", deps=[1]),
        }
        # #1 is not merged yet, so #2 stays blocked.
        result = adl.compute_ready(issues, concurrency=3)
        self.assertEqual(result["ready"], [])

        issues["1"]["status"] = "merged"
        result = adl.compute_ready(issues, concurrency=3)
        self.assertEqual(result["ready"], [2])

    def test_in_flight_consumes_concurrency_budget(self):
        issues = {
            "1": _issue(1, "implementing"),
            "2": _issue(2, "implementing"),
            "3": _issue(3, "analyzed"),
            "4": _issue(4, "analyzed"),
        }
        result = adl.compute_ready(issues, concurrency=2)
        # Two slots already used by implementing issues -> no capacity left.
        self.assertEqual(result["in_flight"], 2)
        self.assertEqual(result["capacity"], 0)
        self.assertEqual(result["ready"], [])

    def test_ready_truncated_to_capacity_lowest_numbers_first(self):
        issues = {
            "5": _issue(5, "analyzed"),
            "3": _issue(3, "analyzed"),
            "9": _issue(9, "analyzed"),
        }
        result = adl.compute_ready(issues, concurrency=2)
        self.assertEqual(result["capacity"], 2)
        # Deterministic ordering by issue number.
        self.assertEqual(result["ready"], [3, 5])

    def test_pr_open_does_not_consume_dev_concurrency(self):
        # Once a PR is open the issue is in monitoring, not active worktree
        # development, so it must not block new implementation work.
        issues = {
            "1": _issue(1, "pr_open"),
            "2": _issue(2, "analyzed"),
        }
        result = adl.compute_ready(issues, concurrency=1)
        self.assertEqual(result["in_flight"], 0)
        self.assertEqual(result["ready"], [2])

    def test_cancelled_dep_blocks_dependent(self):
        issues = {
            "1": _issue(1, "cancelled"),
            "2": _issue(2, "analyzed", deps=[1]),
        }
        result = adl.compute_ready(issues, concurrency=3)
        # A dependency that will never merge leaves the dependent blocked for
        # the human/Claude to re-plan rather than silently dispatching it.
        self.assertEqual(result["ready"], [])


def _sample_state():
    return {
        "title": "AutoDevLoop: 2026/06/18",
        "created": "2026/06/18",
        "tracking_issue": 7,
        "status": "running",
        "config": {
            "base_branch": "main",
            "merge_target": "main",
            "labels": ["auto-ok"],
            "concurrency": 3,
            "auto_merge": "conditional",
            "reviewers": ["claude"],
            "perspectives": ["correctness", "tests"],
        },
        "issues": {
            "12": {
                "number": 12, "title": "data model", "status": "merged",
                "deps": [], "branch": "auto/issue-12", "worktree": "",
                "pr_number": 100, "issue_watermark": "", "pr_watermark": "",
                "note": "", "updated_at": "2026-06-18T17:20:00+0900",
            },
            "13": {
                "number": 13, "title": "uses model", "status": "implementing",
                "deps": [12], "branch": "auto/issue-13", "worktree": "/wt/13",
                "pr_number": None, "issue_watermark": "", "pr_watermark": "",
                "note": "needs | escaping", "updated_at": "2026-06-18T17:25:00+0900",
            },
        },
    }


class BodyRoundTripTests(unittest.TestCase):
    def test_parse_recovers_rendered_state_exactly(self):
        state = _sample_state()
        body = adl.render_body(state)
        self.assertEqual(adl.parse_body(body), state)

    def test_rendered_body_contains_human_table(self):
        body = adl.render_body(_sample_state())
        self.assertIn("| # | title | status |", body)
        self.assertIn("#12", body)
        self.assertIn("data model", body)
        # The machine block must be a fenced json block so humans can read it.
        self.assertIn("```json", body)

    def test_table_escapes_pipe_in_note(self):
        # A raw '|' in a note would break the markdown table layout.
        body = adl.render_body(_sample_state())
        table_region = body.split("```json")[0]
        self.assertNotIn("needs | escaping", table_region)
        self.assertIn("needs \\| escaping", table_region)

    def test_parse_rejects_body_without_state_block(self):
        # A human clearing the fenced block must surface as an error, not a
        # silent reset. parse_body raises SystemExit (the helper's CLI-error
        # convention), which is a BaseException, not an Exception.
        with self.assertRaises(SystemExit):
            adl.parse_body("# just a heading\n\nno state here\n")


if __name__ == "__main__":
    unittest.main()
