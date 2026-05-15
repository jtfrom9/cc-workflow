#!/usr/bin/env python3
"""Background worker invoked by relocate_plan / save_prompt_as_task / checkpoint.

Calls ``claude -p`` to generate a Japanese summary of plan.md and overwrites
summary.md. On failure, writes a diagnostic-rich summary.md so the user can
see exactly what went wrong (exit code, stderr, exception) instead of a bare
"failed" message.

Usage:
    _summarize_worker.py <plan_md_path> <summary_md_path>
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _common  # noqa: E402


def write_failure(
    summary_path: Path,
    *,
    returncode: int | None = None,
    stderr: str | None = None,
    stdout: str | None = None,
    exception: BaseException | None = None,
) -> None:
    """Write an informative failure note to summary.md."""
    lines: list[str] = [
        "# Summary",
        "",
        "(要約の自動生成に失敗しました。)",
        "",
    ]
    if exception is not None:
        lines.append(f"- 例外: `{type(exception).__name__}`: {exception}")
    if returncode is not None:
        lines.append(f"- `claude -p` 終了コード: `{returncode}`")
    if stdout is not None and stdout.strip():
        lines.append("- `claude -p` stdout (先頭 500 字):")
        lines.append("")
        lines.append("```")
        lines.append(stdout[:500])
        lines.append("```")
    if stderr is not None and stderr.strip():
        lines.append("- `claude -p` stderr (先頭 1000 字):")
        lines.append("")
        lines.append("```")
        lines.append(stderr[:1000])
        lines.append("```")
    lines.append("")
    lines.append("再生成: `/jtfrom9-cc-workflow:summarise <taskId>`")
    summary_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    if len(sys.argv) < 3:
        return 1
    plan_path = Path(sys.argv[1])
    summary_path = Path(sys.argv[2])

    try:
        plan_text = plan_path.read_text(encoding="utf-8")
    except OSError as e:
        write_failure(summary_path, exception=e)
        return 0

    prompt = (
        "次の plan を要約してください。\n\n"
        "出力ルール (厳守):\n"
        "- 日本語の箇条書き、**最大 3 項目** まで\n"
        "- 各項目は 1 行 (60〜100 字程度)\n"
        "- ぱっと読んで「何をしているか」「何が重要か」が分かる粒度に。固有名詞・ファイル名は具体的に\n"
        "- 重要度が高い項目を先に\n"
        "- 出力は箇条書きのみ。見出し、前置き、後置き、コードブロック禁止\n"
        "- 各項目は `- ` で始める\n\n"
        "対象 plan:\n\n"
        + plan_text
    )

    cmd = _common.claude_command() + ["-p", prompt]
    try:
        r = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=180,
            stdin=subprocess.DEVNULL,
        )
    except Exception as e:
        write_failure(summary_path, exception=e)
        return 0

    summary = (r.stdout or "").strip()

    if r.returncode != 0 or not summary:
        write_failure(
            summary_path,
            returncode=r.returncode,
            stderr=r.stderr,
            stdout=r.stdout,
        )
        return 0

    summary_path.write_text(f"# Summary\n\n{summary}\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
