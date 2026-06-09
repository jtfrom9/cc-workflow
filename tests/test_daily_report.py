#!/usr/bin/env python3
"""Unit tests for the pure logic in ``tools/daily_report.py``.

Filesystem scanning is side-effecting and is not exercised here; only the
deterministic parsing/extraction/rendering helpers are.

Run from the repo root::

    python3 -m unittest discover -s tests
"""

from __future__ import annotations

import sys
import unittest
from datetime import date, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import daily_report as dr  # noqa: E402

JST = timezone(timedelta(hours=9))


class LocalDateTests(unittest.TestCase):
    def test_utc_z_suffix_converts_to_local_date(self):
        # 05:45 UTC == 14:45 JST, same calendar day
        self.assertEqual(dr.to_local_date("2026-06-09T05:45:25.346Z", JST), date(2026, 6, 9))

    def test_utc_evening_rolls_into_next_local_day(self):
        # 20:00 UTC on the 8th == 05:00 JST on the 9th
        self.assertEqual(dr.to_local_date("2026-06-08T20:00:00.000Z", JST), date(2026, 6, 9))

    def test_explicit_offset_is_respected(self):
        self.assertEqual(dr.to_local_date("2026-06-09T00:00:00+09:00", JST), date(2026, 6, 9))

    def test_empty_or_garbage_is_none(self):
        self.assertIsNone(dr.to_local_date("", JST))
        self.assertIsNone(dr.to_local_date("not-a-date", JST))
        self.assertIsNone(dr.to_local_date(None, JST))

    def test_hm_formats_local_clock(self):
        self.assertEqual(dr.to_local_hm("2026-06-09T05:45:25.346Z", JST), "14:45")
        self.assertEqual(dr.to_local_hm("bad", JST), "")


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
    def test_empty_renders_placeholder(self):
        out = dr.render({}, [], date(2026, 6, 9), 80)
        self.assertIn("2026-06-09", out)
        self.assertIn("no transcript activity", out)

    def test_groups_by_project_and_lists_turns(self):
        key = ("cc-workflow", "abcdef12-0000")
        sessions = {key: [("14:45", "user", "fix the bug"), ("14:46", "assistant", "done")]}
        out = dr.render(sessions, [key], date(2026, 6, 9), 80)
        self.assertIn("## project: cc-workflow", out)
        self.assertIn("- [14:45] user: fix the bug", out)
        self.assertIn("- [14:46] assistant: done", out)


if __name__ == "__main__":
    unittest.main()
