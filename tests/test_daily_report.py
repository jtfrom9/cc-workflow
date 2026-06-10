#!/usr/bin/env python3
"""Unit tests for ``tools/daily_report.py``.

The deterministic parsing/extraction/rendering helpers are covered here,
along with ``collect``'s project-scoping behavior (exercised against a
temporary projects root).

Run from the repo root::

    python3 -m unittest discover -s tests
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import daily_report as dr  # noqa: E402

JST = timezone(timedelta(hours=9))


class TimestampTests(unittest.TestCase):
    def test_hm_formats_local_clock(self):
        self.assertEqual(dr.to_local_hm("2026-06-09T05:45:25.346Z", JST), "14:45")
        self.assertEqual(dr.to_local_hm("bad", JST), "")


class WindowTests(unittest.TestCase):
    """``in_window`` decides membership in a half-open ``[start, end)`` range
    of tz-aware instants, regardless of the timestamp's own zone."""

    START = datetime(2026, 6, 9, 11, 0, tzinfo=JST)
    END = datetime(2026, 6, 10, 11, 0, tzinfo=JST)

    def test_inside_window_is_true(self):
        # 05:45 UTC == 14:45 JST, within [11:00 .. 11:00 next day)
        self.assertTrue(dr.in_window("2026-06-09T05:45:25Z", self.START, self.END))

    def test_before_window_is_false(self):
        # 01:00 UTC == 10:00 JST, before the 11:00 start
        self.assertFalse(dr.in_window("2026-06-09T01:00:00Z", self.START, self.END))

    def test_start_is_inclusive(self):
        # 02:00 UTC == 11:00 JST == start
        self.assertTrue(dr.in_window("2026-06-09T02:00:00Z", self.START, self.END))

    def test_end_is_exclusive(self):
        # 02:00 UTC next day == 11:00 JST == end
        self.assertFalse(dr.in_window("2026-06-10T02:00:00Z", self.START, self.END))

    def test_garbage_timestamp_is_false(self):
        self.assertFalse(dr.in_window("not-a-date", self.START, self.END))
        self.assertFalse(dr.in_window("", self.START, self.END))
        self.assertFalse(dr.in_window(None, self.START, self.END))


class MessageTextTests(unittest.TestCase):
    def test_user_plain_string(self):
        self.assertEqual(dr.message_text("user", "hello"), "hello")

    def test_user_whitespace_only_is_none(self):
        self.assertIsNone(dr.message_text("user", "   \n  "))

    def test_user_text_blocks_join(self):
        content = [{"type": "text", "text": "first"}, {"type": "text", "text": "second"}]
        self.assertEqual(dr.message_text("user", content), "first\nsecond")

    def test_user_tool_result_turn_is_skipped(self):
        content = [{"type": "tool_result", "content": "stdout"}]
        self.assertIsNone(dr.message_text("user", content))

    def test_assistant_keeps_text_drops_thinking_and_tool_use(self):
        content = [
            {"type": "thinking", "thinking": "secret"},
            {"type": "text", "text": "the answer"},
            {"type": "tool_use", "name": "Bash"},
        ]
        self.assertEqual(dr.message_text("assistant", content), "the answer")

    def test_assistant_thinking_only_is_none(self):
        content = [{"type": "thinking", "thinking": "secret"}]
        self.assertIsNone(dr.message_text("assistant", content))

    def test_unknown_role_is_none(self):
        self.assertIsNone(dr.message_text("system", "x"))


class MetaTextTests(unittest.TestCase):
    def test_command_and_system_wrappers_are_meta(self):
        self.assertTrue(dr.is_meta_text("<command-name>/foo</command-name>"))
        self.assertTrue(dr.is_meta_text("<local-command-stdout>...</local-command-stdout>"))
        self.assertTrue(dr.is_meta_text("<system-reminder>noise</system-reminder>"))

    def test_real_prompt_is_not_meta(self):
        self.assertFalse(dr.is_meta_text("今日のセッションを要約して"))


class TruncateTests(unittest.TestCase):
    def test_short_text_unchanged(self):
        self.assertEqual(dr.truncate("abc", 10), "abc")

    def test_long_text_gets_ellipsis_within_limit(self):
        out = dr.truncate("abcdefghij", 5)
        self.assertLessEqual(len(out), 5)
        self.assertTrue(out.endswith("…"))


class RenderTests(unittest.TestCase):
    START = datetime(2026, 6, 9, 11, 0, tzinfo=JST)
    END = datetime(2026, 6, 10, 11, 0, tzinfo=JST)

    def test_empty_renders_placeholder(self):
        out = dr.render({}, [], self.START, self.END, 80)
        self.assertIn("no transcript activity", out)

    def test_header_shows_window_bounds(self):
        out = dr.render({}, [], self.START, self.END, 80)
        self.assertIn("2026-06-09 11:00", out)
        self.assertIn("2026-06-10 11:00", out)

    def test_groups_by_project_and_lists_turns(self):
        key = ("cc-workflow", "abcdef12-0000")
        sessions = {key: [("14:45", "user", "fix the bug"), ("14:46", "assistant", "done")]}
        out = dr.render(sessions, [key], self.START, self.END, 80)
        self.assertIn("## project: cc-workflow", out)
        self.assertIn("- [14:45] user: fix the bug", out)
        self.assertIn("- [14:46] assistant: done", out)

    def test_header_shows_project_scope_when_restricted(self):
        out = dr.render({}, [], self.START, self.END, 80, project="C--work-cc-workflow")
        self.assertIn("C--work-cc-workflow", out)


class CollectScopeTests(unittest.TestCase):
    START = datetime(2026, 6, 9, 0, 0, tzinfo=JST)
    END = datetime(2026, 6, 10, 0, 0, tzinfo=JST)

    def _write(self, root, project, session, ts, role, text):
        pdir = root / project
        pdir.mkdir(parents=True, exist_ok=True)
        rec = {"timestamp": ts, "sessionId": session,
               "message": {"role": role, "content": text}}
        with (pdir / f"{session}.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")

    def test_project_filter_scans_only_named_project(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            # 05:00 UTC == 14:00 JST, inside the JST-9th window
            self._write(root, "projA", "s1", "2026-06-09T05:00:00Z", "user", "in A")
            self._write(root, "projB", "s2", "2026-06-09T05:00:00Z", "user", "in B")
            _, order = dr.collect(root, self.START, self.END, project="projA")
            self.assertEqual([k[0] for k in order], ["projA"])

    def test_no_filter_scans_all_projects(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self._write(root, "projA", "s1", "2026-06-09T05:00:00Z", "user", "in A")
            self._write(root, "projB", "s2", "2026-06-09T05:00:00Z", "user", "in B")
            _, order = dr.collect(root, self.START, self.END)
            self.assertEqual(sorted(k[0] for k in order), ["projA", "projB"])


if __name__ == "__main__":
    unittest.main()
