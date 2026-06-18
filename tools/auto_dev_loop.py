#!/usr/bin/env python3
"""auto_dev_loop — deterministic state transforms for the auto-dev-loop skill.

The skill (``skills/auto-dev-loop/SKILL.md``) drives all *judgement* and all
*side effects*: it talks to GitHub via ``gh`` (creating the tracking issue,
reading/writing its description, opening PRs, merging), decides which issues
are feasible, detects dependencies, implements via auto-review-loop, and
triages issue/PR comments.

This helper owns only the *deterministic, side-effect-free* pieces:

  - ``compute_ready`` — given the managed issues and the concurrency cap,
    which analyzed issues may start *now* (dependencies satisfied + a free
    development slot),
  - ``render_body`` / ``parse_body`` — the single source of truth is the
    tracking issue's **description**, which holds a human-readable progress
    table plus a fenced ``json`` block with the full machine state. These two
    functions round-trip a state dict to that body and back.

There is **no local persistence**: the GitHub tracking issue (found by the
``auto-dev-loop`` label) is the source of truth and the cross-machine
singleton lock. Per pass the skill fetches the issue body, the subcommands
here operate on an *ephemeral* working JSON file (``--state``), and the skill
renders the body back and writes it via ``gh``. stdlib only; never calls gh.

Subcommands (all print ``key=value`` lines on stdout):

    new-state    --state f --base b --merge-target m --labels a,b \
                 --concurrency N --auto-merge off|conditional|green \
                 --reviewers ... --perspectives ... --tracking-issue N \
                 --title t --created YYYY/MM/DD
    load-body    --body-file f --state out       (extract state from a body)
    render       --state f                        (print the issue body)
    upsert-issues --state f --json payload
    update-issue --state f --number N [...]
    watermark    --state f --kind issue|pr --number N --ts iso
    set-run-status --state f --status running|stopped|done
    next-ready   --state f
    summary      --state f
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _common  # noqa: E402


# Issue lifecycle statuses.
#   discovered  -> seen via gh, not yet analyzed
#   analyzed    -> feasible, dependencies mapped; dispatchable once deps clear
#   blocked     -> analyzed but held (info missing / needs a human); not started
#   implementing-> a worktree is actively being worked (counts against the cap)
#   pr_open     -> PR raised; in monitoring, no longer using a dev slot
#   merged      -> PR merged; satisfies dependents
#   cancelled   -> dropped (infeasible, or told to stop); never satisfies deps
#   failed      -> abandoned after errors; for the human to look at
DISPATCHABLE = "analyzed"
DEP_SATISFIED = {"merged"}
COUNTS_AS_IN_FLIGHT = {"implementing"}

AUTO_MERGE_POLICIES = ("off", "conditional", "green")

DEFAULT_PERSPECTIVES = [
    "correctness",
    "requirements",
    "security",
    "performance",
    "conventions",
    "tests",
]

STATE_MARKER = "<!-- auto-dev-loop:state — machine-readable; do not edit by hand -->"
_JSON_BLOCK_RE = re.compile(r"```json\s*\n(.*?)\n```", re.DOTALL)


# ----------------------------------------------------------------------
# Pure scheduling logic (unit-tested in tests/test_auto_dev_loop.py)
# ----------------------------------------------------------------------

def compute_ready(issues: dict, concurrency: int) -> dict:
    """Decide which analyzed issues may start *now*.

    An issue is a candidate when its status is ``analyzed``. A candidate is
    *unblocked* when every dependency it lists is in a dependency-satisfying
    state (merged). The number of new starts is bounded by the remaining
    concurrency budget = ``concurrency - (issues already implementing)``.
    PR-open issues are in monitoring, not active development, so they do not
    consume a development slot.

    Returns ``{"ready": [..numbers..], "in_flight": int, "capacity": int}``
    with ``ready`` sorted ascending for deterministic dispatch.
    """
    in_flight = sum(
        1 for it in issues.values() if it.get("status") in COUNTS_AS_IN_FLIGHT
    )
    capacity = max(0, concurrency - in_flight)

    def dep_done(dep_number: int) -> bool:
        dep = issues.get(str(dep_number))
        return bool(dep) and dep.get("status") in DEP_SATISFIED

    candidates = []
    for it in issues.values():
        if it.get("status") != DISPATCHABLE:
            continue
        if all(dep_done(d) for d in it.get("deps", [])):
            candidates.append(it["number"])

    candidates.sort()
    return {
        "ready": candidates[:capacity],
        "in_flight": in_flight,
        "capacity": capacity,
    }


# ----------------------------------------------------------------------
# Pure body <-> state transform (the tracking issue description)
# ----------------------------------------------------------------------

def _cell(text: str) -> str:
    """Make a value safe to drop into a markdown table cell."""
    return str(text or "").replace("|", "\\|").replace("\n", " ").strip()


def render_body(state: dict) -> str:
    """Render the tracking issue description: a human table + the fenced state.

    The table is what a human sees when looking at the issue; the fenced
    ``json`` block is the authoritative machine state that :func:`parse_body`
    reads back. Both live in the same description so the issue *is* the source
    of truth.
    """
    cfg = state.get("config", {})
    issues = state.get("issues", {})
    sched = compute_ready(issues, cfg.get("concurrency", 1))

    out: list[str] = []
    out.append(f"# {state.get('title', 'AutoDevLoop')}")
    out.append("")
    out.append(
        f"- base: `{cfg.get('base_branch')}` → merge: `{cfg.get('merge_target')}`"
    )
    out.append(
        f"- labels: {', '.join(cfg.get('labels', [])) or '—'} "
        f"| concurrency: {cfg.get('concurrency')} "
        f"| auto-merge: `{cfg.get('auto_merge')}`"
    )
    out.append(
        f"- reviewers: {', '.join(cfg.get('reviewers', []))} "
        f"| perspectives: {', '.join(cfg.get('perspectives', []))}"
    )
    out.append(f"- run status: **{state.get('status', 'running')}**")
    ready = ", ".join(f"#{n}" for n in sched["ready"]) or "—"
    out.append(
        f"- in_flight: {sched['in_flight']} / capacity: {sched['capacity']} "
        f"/ ready now: {ready}"
    )
    out.append("")
    out.append("## Issues")
    out.append("")
    out.append("| # | title | status | deps | PR | updated | note |")
    out.append("|---|---|---|---|---|---|---|")
    for key in sorted(issues, key=lambda k: int(k)):
        it = issues[key]
        deps = ", ".join(f"#{d}" for d in it.get("deps", [])) or "—"
        pr = f"#{it['pr_number']}" if it.get("pr_number") else "—"
        upd = (it.get("updated_at", "") or "")[:16].replace("T", " ")
        out.append(
            f"| #{it['number']} | {_cell(it.get('title'))} | {it.get('status', '')} "
            f"| {deps} | {pr} | {upd} | {_cell(it.get('note'))} |"
        )
    out.append("")
    out.append(STATE_MARKER)
    out.append("```json")
    out.append(json.dumps(state, ensure_ascii=False, indent=2))
    out.append("```")
    return "\n".join(out) + "\n"


def parse_body(body: str) -> dict:
    """Recover the state dict from a tracking issue body.

    Reads the last fenced ``json`` block (the one :func:`render_body` writes
    under :data:`STATE_MARKER`). Raises if no machine-readable block is found,
    so a human accidentally clearing it surfaces as an error rather than a
    silent reset.
    """
    blocks = _JSON_BLOCK_RE.findall(body or "")
    if not blocks:
        raise SystemExit(
            "no machine-readable state block found in the tracking issue body"
        )
    return json.loads(blocks[-1])


# ----------------------------------------------------------------------
# Ephemeral working-state file I/O
# ----------------------------------------------------------------------

def load_state_file(path: str) -> dict:
    p = Path(path)
    if not p.is_file():
        raise SystemExit(f"no working state at {path}; run `load-body`/`new-state` first")
    return json.loads(p.read_text(encoding="utf-8"))


def save_state_file(path: str, state: dict) -> None:
    Path(path).write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _split_csv(raw: str) -> list[str]:
    return [item.strip() for item in (raw or "").split(",") if item.strip()]


# ----------------------------------------------------------------------
# Subcommands
# ----------------------------------------------------------------------

def cmd_new_state(args) -> int:
    if args.auto_merge not in AUTO_MERGE_POLICIES:
        raise SystemExit(
            f"--auto-merge must be one of {', '.join(AUTO_MERGE_POLICIES)}"
        )
    state = {
        "title": args.title or "AutoDevLoop",
        "created": args.created,
        "tracking_issue": int(args.tracking_issue) if args.tracking_issue else None,
        "status": "running",
        "config": {
            "base_branch": args.base.strip(),
            "merge_target": (args.merge_target or args.base).strip(),
            "labels": _split_csv(args.labels),
            "concurrency": int(args.concurrency),
            "auto_merge": args.auto_merge,
            "reviewers": _split_csv(args.reviewers) or ["claude"],
            "perspectives": _split_csv(args.perspectives) or list(DEFAULT_PERSPECTIVES),
        },
        "issues": {},
    }
    save_state_file(args.state, state)
    print(f"state={args.state}")
    print(f"tracking_issue={state['tracking_issue']}")
    print(f"title={state['title']}")
    return 0


def cmd_load_body(args) -> int:
    body = Path(args.body_file).read_text(encoding="utf-8")
    state = parse_body(body)
    save_state_file(args.state, state)
    print(f"state={args.state}")
    print(f"tracking_issue={state.get('tracking_issue')}")
    print(f"status={state.get('status')}")
    print(f"total_issues={len(state.get('issues', {}))}")
    return 0


def cmd_render(args) -> int:
    state = load_state_file(args.state)
    sys.stdout.write(render_body(state))
    return 0


def cmd_upsert_issues(args) -> int:
    state = load_state_file(args.state)
    issues = state.setdefault("issues", {})
    payload = json.loads(Path(args.json).read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        payload = payload.get("issues", [])

    added = 0
    for item in payload:
        num = item.get("number")
        if num is None:
            continue
        key = str(num)
        existing = issues.get(key, {})
        issues[key] = {
            "number": int(num),
            "title": item.get("title", existing.get("title", "")),
            "status": item.get("status", existing.get("status", "discovered")),
            "deps": item.get("deps", existing.get("deps", [])),
            "note": item.get("note", existing.get("note", "")),
            "branch": existing.get("branch", ""),
            "worktree": existing.get("worktree", ""),
            "pr_number": existing.get("pr_number"),
            "issue_watermark": existing.get("issue_watermark", ""),
            "pr_watermark": existing.get("pr_watermark", ""),
            "updated_at": _common.now_iso(),
        }
        added += 1

    save_state_file(args.state, state)
    print(f"upserted={added}")
    print(f"total_issues={len(issues)}")
    return 0


def cmd_update_issue(args) -> int:
    state = load_state_file(args.state)
    it = state.get("issues", {}).get(str(args.number))
    if it is None:
        raise SystemExit(f"issue #{args.number} is not managed")

    if args.status is not None:
        it["status"] = args.status
    if args.branch is not None:
        it["branch"] = args.branch
    if args.worktree is not None:
        it["worktree"] = args.worktree
    if args.pr is not None:
        it["pr_number"] = int(args.pr)
    if args.note is not None:
        it["note"] = args.note
    if args.clear_deps:
        it["deps"] = []
    if args.add_dep is not None:
        deps = it.setdefault("deps", [])
        if int(args.add_dep) not in deps:
            deps.append(int(args.add_dep))
    it["updated_at"] = _common.now_iso()

    save_state_file(args.state, state)
    print(f"issue={args.number}")
    print(f"status={it['status']}")
    print(f"pr_number={it.get('pr_number')}")
    print(f"deps={','.join(str(d) for d in it.get('deps', []))}")
    return 0


def cmd_watermark(args) -> int:
    state = load_state_file(args.state)
    it = state.get("issues", {}).get(str(args.number))
    if it is None:
        raise SystemExit(f"issue #{args.number} is not managed")
    field = "issue_watermark" if args.kind == "issue" else "pr_watermark"
    it[field] = args.ts
    it["updated_at"] = _common.now_iso()
    save_state_file(args.state, state)
    print(f"issue={args.number}")
    print(f"{field}={args.ts}")
    return 0


def cmd_set_run_status(args) -> int:
    if args.status not in ("running", "stopped", "done"):
        raise SystemExit("--status must be running | stopped | done")
    state = load_state_file(args.state)
    state["status"] = args.status
    save_state_file(args.state, state)
    print(f"status={args.status}")
    return 0


def cmd_next_ready(args) -> int:
    state = load_state_file(args.state)
    cfg = state["config"]
    result = compute_ready(state.get("issues", {}), cfg.get("concurrency", 1))
    print(f"ready={','.join(str(n) for n in result['ready'])}")
    print(f"ready_count={len(result['ready'])}")
    print(f"in_flight={result['in_flight']}")
    print(f"capacity={result['capacity']}")
    return 0


def cmd_summary(args) -> int:
    state = load_state_file(args.state)
    issues = state.get("issues", {})
    cfg = state["config"]
    sched = compute_ready(issues, cfg.get("concurrency", 1))

    print(f"tracking_issue={state.get('tracking_issue')}")
    print(f"status={state.get('status')}")
    print(f"auto_merge={cfg.get('auto_merge')}")
    print(f"concurrency={cfg.get('concurrency')}")
    print(f"in_flight={sched['in_flight']}")
    print(f"capacity={sched['capacity']}")
    print(f"ready={','.join(str(n) for n in sched['ready'])}")
    print(f"total_issues={len(issues)}")

    tally: dict[str, int] = {}
    for it in issues.values():
        st = it.get("status", "?")
        tally[st] = tally.get(st, 0) + 1
    for st in sorted(tally):
        print(f"count.{st}={tally[st]}")

    # When everything is in a terminal state and nothing can start, the loop
    # has converged; the skill uses this to decide done vs keep-monitoring.
    terminal = {"merged", "cancelled"}
    active = [it for it in issues.values() if it.get("status") not in terminal]
    print(f"active_issues={len(active)}")
    return 0


# ----------------------------------------------------------------------
# Entry point
# ----------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="auto_dev_loop")
    sub = parser.add_subparsers(dest="command", required=True)

    p_new = sub.add_parser("new-state", help="create a fresh working state")
    p_new.add_argument("--state", required=True, help="working state file to write")
    p_new.add_argument("--base", required=True)
    p_new.add_argument("--merge-target", default="")
    p_new.add_argument("--labels", default="")
    p_new.add_argument("--concurrency", default="3")
    p_new.add_argument("--auto-merge", default="off")
    p_new.add_argument("--reviewers", default="claude")
    p_new.add_argument("--perspectives", default="")
    p_new.add_argument("--tracking-issue", default="")
    p_new.add_argument("--title", default="")
    p_new.add_argument("--created", default="")
    p_new.set_defaults(func=cmd_new_state)

    p_lb = sub.add_parser("load-body", help="extract state from a tracking issue body")
    p_lb.add_argument("--body-file", required=True)
    p_lb.add_argument("--state", required=True, help="working state file to write")
    p_lb.set_defaults(func=cmd_load_body)

    p_rb = sub.add_parser("render", help="print the tracking issue body for the state")
    p_rb.add_argument("--state", required=True)
    p_rb.set_defaults(func=cmd_render)

    p_up = sub.add_parser("upsert-issues", help="merge analyzed issues into state")
    p_up.add_argument("--state", required=True)
    p_up.add_argument("--json", required=True, help="path to the issues JSON payload")
    p_up.set_defaults(func=cmd_upsert_issues)

    p_ui = sub.add_parser("update-issue", help="update one managed issue")
    p_ui.add_argument("--state", required=True)
    p_ui.add_argument("--number", required=True, type=int)
    p_ui.add_argument("--status", default=None)
    p_ui.add_argument("--branch", default=None)
    p_ui.add_argument("--worktree", default=None)
    p_ui.add_argument("--pr", default=None, type=int)
    p_ui.add_argument("--note", default=None)
    p_ui.add_argument("--add-dep", default=None, type=int)
    p_ui.add_argument("--clear-deps", action="store_true")
    p_ui.set_defaults(func=cmd_update_issue)

    p_wm = sub.add_parser("watermark", help="record a comment watermark")
    p_wm.add_argument("--state", required=True)
    p_wm.add_argument("--kind", required=True, choices=["issue", "pr"])
    p_wm.add_argument("--number", required=True, type=int)
    p_wm.add_argument("--ts", required=True, help="ISO timestamp of last-seen comment")
    p_wm.set_defaults(func=cmd_watermark)

    p_rs = sub.add_parser("set-run-status", help="set the run status")
    p_rs.add_argument("--state", required=True)
    p_rs.add_argument("--status", required=True, help="running | stopped | done")
    p_rs.set_defaults(func=cmd_set_run_status)

    p_nr = sub.add_parser("next-ready", help="compute dispatchable issues now")
    p_nr.add_argument("--state", required=True)
    p_nr.set_defaults(func=cmd_next_ready)

    p_sm = sub.add_parser("summary", help="summarize the working state")
    p_sm.add_argument("--state", required=True)
    p_sm.set_defaults(func=cmd_summary)

    return parser


def main() -> int:
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
