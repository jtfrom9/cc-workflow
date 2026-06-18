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

import json
import re
import sys
import tempfile
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

    def test_machine_state_is_hidden_inside_html_comment(self):
        # Humans should see only the progress table; the machine state is
        # wrapped in an HTML comment so GitHub does not render it, while
        # parse_body still recovers it from the raw body.
        body = adl.render_body(_sample_state())
        comments = re.findall(r"<!--(.*?)-->", body, re.DOTALL)
        self.assertTrue(any("```json" in c for c in comments))
        self.assertEqual(adl.parse_body(body), _sample_state())

    def test_parse_rejects_body_without_state_block(self):
        # A human clearing the fenced block must surface as an error, not a
        # silent reset. parse_body raises SystemExit (the helper's CLI-error
        # convention), which is a BaseException, not an Exception.
        with self.assertRaises(SystemExit):
            adl.parse_body("# just a heading\n\nno state here\n")


class BlockedFingerprintTests(unittest.TestCase):
    """The blocked-reason fingerprint lets the skill skip re-commenting the
    same blocker on an issue — even across a *different* tracking issue, where
    the working state starts empty and the only durable signal is the marker
    already embedded in the issue's own comments."""

    def test_fingerprint_is_stable_and_whitespace_case_insensitive(self):
        a = adl.blocked_fingerprint("Scope unclear: which screens?")
        b = adl.blocked_fingerprint("  scope unclear:   WHICH screens?  ")
        self.assertTrue(a)
        self.assertEqual(a, b)

    def test_different_reasons_get_different_fingerprints(self):
        self.assertNotEqual(
            adl.blocked_fingerprint("missing acceptance criteria"),
            adl.blocked_fingerprint("needs an architecture decision"),
        )

    def test_marker_embeds_the_fingerprint(self):
        fp = adl.blocked_fingerprint("missing acceptance criteria")
        marker = adl.blocked_marker(fp)
        self.assertIn(fp, marker)
        # Stable, greppable token so the skill can detect a prior comment.
        self.assertIn("auto-dev-loop:blocked", marker)


class TrackingTitleTests(unittest.TestCase):
    """Same-day tracking issues past the first get an ordinal suffix so a fresh
    run started after an earlier one closed is distinguishable in the title."""

    def test_first_of_the_day_has_no_suffix(self):
        self.assertEqual(
            adl.tracking_title("2026/06/18", 1), "AutoDevLoop: 2026/06/18"
        )

    def test_later_runs_get_ordinal_suffix(self):
        self.assertEqual(
            adl.tracking_title("2026/06/18", 2), "AutoDevLoop: 2026/06/18 (.2nd)"
        )
        self.assertEqual(
            adl.tracking_title("2026/06/18", 3), "AutoDevLoop: 2026/06/18 (.3rd)"
        )
        self.assertEqual(
            adl.tracking_title("2026/06/18", 4), "AutoDevLoop: 2026/06/18 (.4th)"
        )

    def test_ordinal_handles_the_teens_and_ones(self):
        self.assertEqual(adl._ordinal(11), "11th")
        self.assertEqual(adl._ordinal(12), "12th")
        self.assertEqual(adl._ordinal(13), "13th")
        self.assertEqual(adl._ordinal(21), "21st")
        self.assertEqual(adl._ordinal(22), "22nd")


class UpdateIssueBlockedFpTests(unittest.TestCase):
    def test_update_issue_records_blocked_comment_fingerprint(self):
        state = {
            "title": "t", "created": "", "tracking_issue": 1, "status": "running",
            "config": {
                "base_branch": "main", "merge_target": "main", "labels": [],
                "concurrency": 1, "auto_merge": "off",
                "reviewers": ["claude"], "perspectives": ["tests"],
            },
            "issues": {
                "9": {
                    "number": 9, "title": "x", "status": "blocked", "deps": [],
                    "branch": "", "worktree": "", "pr_number": None,
                    "issue_watermark": "", "pr_watermark": "",
                    "blocked_comment_fp": "", "note": "scope unclear",
                    "updated_at": "2026-06-18T00:00:00+0900",
                },
            },
        }
        with tempfile.TemporaryDirectory() as d:
            sf = Path(d) / "state.json"
            sf.write_text(json.dumps(state), encoding="utf-8")
            args = adl.build_parser().parse_args(
                ["update-issue", "--state", str(sf), "--number", "9",
                 "--blocked-fp", "abc123"]
            )
            args.func(args)
            saved = json.loads(sf.read_text(encoding="utf-8"))
        self.assertEqual(saved["issues"]["9"]["blocked_comment_fp"], "abc123")


if __name__ == "__main__":
    unittest.main()
