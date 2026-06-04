#!/usr/bin/env python3
"""review_loop — deterministic state I/O for the auto-review-loop skill.

The skill (``skills/auto-review-loop/SKILL.md``) drives all *judgement*
(triage, deciding what is a must-fix, writing fixes). This helper only owns
the *bookkeeping* that must survive across the loop so the run stays
observable (NFR-2) and re-review can be narrowed deterministically (FR-7):

  - which reviewers x perspectives were selected at start (FR-1.4),
  - how many review rounds have happened and which pairs ran each round,
  - which pairs produced accepted must-fix findings last round (so the next
    round re-reviews only those, FR-7),
  - whether the round cap has been reached (FR-6 circuit breaker).

Everything is stored under ``~/.cc-workflow/reviews/<project>/<run-id>/`` so
the repository working tree is never touched (matching the rest of the
plugin's storage policy). Full review text is written by the skill into
``round-<n>/<reviewer>-<perspective>.md`` next to ``state.json`` (FR-8.4);
this helper only records pointers and the structured round summary.

Subcommands (all print ``key=value`` lines on stdout):

    init   --reviewers a,b --perspectives x,y [--title t]
    start-round
    record-round --json <file>
    circuit-check
    status
    finish --status completed|handed_back

``start-round`` / ``record-round`` / ``circuit-check`` / ``status`` /
``finish`` operate on the "open" run recorded in
``state/<sid>/open_review_run`` unless ``--run <run_id>`` is given.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _common  # noqa: E402


# Initial review + at most two fix->re-review round-trips (FR-6.1). The
# third re-review that still surfaces must-fix findings is round-trip #3,
# which trips the circuit breaker (FR-6.2).
MAX_REVIEW_ROUNDS = 3


# ----------------------------------------------------------------------
# Paths / open-run pointer
# ----------------------------------------------------------------------

def reviews_dir(project: str) -> Path:
    return _common.data_dir() / "reviews" / project


def open_run_marker(session_id: str) -> Path:
    return _common.state_dir_for(session_id) / "open_review_run"


def write_open_run(session_id: str, run_id: str) -> None:
    if not session_id:
        return
    sdir = _common.state_dir_for(session_id)
    sdir.mkdir(parents=True, exist_ok=True)
    open_run_marker(session_id).write_text(f"{run_id}\n", encoding="utf-8")


def read_open_run(session_id: str) -> str:
    if not session_id:
        return ""
    marker = open_run_marker(session_id)
    if not marker.is_file():
        return ""
    try:
        return marker.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def run_dir(project: str, run_id: str) -> Path:
    return reviews_dir(project) / run_id


def state_path(project: str, run_id: str) -> Path:
    return run_dir(project, run_id) / "state.json"


# ----------------------------------------------------------------------
# state.json load / save
# ----------------------------------------------------------------------

def load_state(project: str, run_id: str) -> dict:
    p = state_path(project, run_id)
    if not p.is_file():
        raise FileNotFoundError(f"no review run state at {p}")
    return json.loads(p.read_text(encoding="utf-8"))


def save_state(project: str, run_id: str, state: dict) -> None:
    p = state_path(project, run_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _split_csv(raw: str) -> list[str]:
    return [item.strip() for item in (raw or "").split(",") if item.strip()]


def _pair_key(pair: dict) -> str:
    return f"{pair.get('reviewer', '')}::{pair.get('perspective', '')}"


def _encode_pairs(pairs: list[dict]) -> str:
    """Render a pair list as ``reviewer::perspective,...`` for key=value output."""
    return ",".join(_pair_key(p) for p in pairs)


def _resolve_run(args, project: str, sid: str) -> str:
    run_id = getattr(args, "run", "") or read_open_run(sid)
    if not run_id:
        raise SystemExit(
            "no open review run; pass --run <run_id> or call `init` first"
        )
    return run_id


# ----------------------------------------------------------------------
# Subcommands
# ----------------------------------------------------------------------

def cmd_init(args, project: str, project_root: Path, sid: str) -> int:
    reviewers = _split_csv(args.reviewers)
    perspectives = _split_csv(args.perspectives)
    if not reviewers:
        raise SystemExit("init requires at least one --reviewers value")
    if not perspectives:
        raise SystemExit("init requires at least one --perspectives value")

    now = datetime.now()
    slug = _common.slugify(args.title) or "review"
    run_id = f"{now.strftime('%y%m%d-%H%M%S')}-{slug}"

    state = {
        "run_id": run_id,
        "project": project,
        "project_root": str(project_root),
        "session_id": sid,
        "created_at": _common.now_iso(),
        "reviewers": reviewers,
        "perspectives": perspectives,
        "status": "in_progress",
        "rounds": [],
    }
    save_state(project, run_id, state)
    write_open_run(sid, run_id)

    rdir = run_dir(project, run_id)
    print(f"run_id={run_id}")
    print(f"run_dir={rdir}")
    print(f"state_path={state_path(project, run_id)}")
    print(f"project={project}")
    print(f"session_id={sid}")
    print(f"reviewers={','.join(reviewers)}")
    print(f"perspectives={','.join(perspectives)}")
    print(f"max_review_rounds={MAX_REVIEW_ROUNDS}")
    return 0


def cmd_start_round(args, project: str, project_root: Path, sid: str) -> int:
    run_id = _resolve_run(args, project, sid)
    state = load_state(project, run_id)
    rounds = state.get("rounds", [])
    n = len(rounds) + 1

    if n == 1:
        pairs = [
            {"reviewer": r, "perspective": p}
            for r in state.get("reviewers", [])
            for p in state.get("perspectives", [])
        ]
    else:
        # FR-7: re-review only the reviewer x perspective pairs that produced
        # accepted must-fix findings in the previous round.
        pairs = list(rounds[-1].get("with_findings", []))

    over_cap = n > MAX_REVIEW_ROUNDS
    if over_cap:
        # Guard: the skill should have circuit-broken before this. Do not
        # append a round; just report so the caller can hand back (FR-6.3).
        print(f"round={n}")
        print("over_cap=1")
        print(f"pairs={_encode_pairs(pairs)}")
        return 0

    round_dir = run_dir(project, run_id) / f"round-{n}"
    round_dir.mkdir(parents=True, exist_ok=True)

    rounds.append(
        {
            "n": n,
            "ran": pairs,
            "findings": [],
            "with_findings": [],
            "resolved": None,
        }
    )
    state["rounds"] = rounds
    save_state(project, run_id, state)

    print(f"run_id={run_id}")
    print(f"round={n}")
    print("over_cap=0")
    print(f"round_dir={round_dir}")
    print(f"pairs={_encode_pairs(pairs)}")
    print(f"pair_count={len(pairs)}")
    return 0


def cmd_record_round(args, project: str, project_root: Path, sid: str) -> int:
    run_id = _resolve_run(args, project, sid)
    state = load_state(project, run_id)
    rounds = state.get("rounds", [])
    if not rounds:
        raise SystemExit("no round to record; call `start-round` first")

    payload = json.loads(Path(args.json).read_text(encoding="utf-8"))
    # Target the round named in the payload, else the latest open round.
    target_n = payload.get("n") or rounds[-1]["n"]
    target = next((r for r in rounds if r["n"] == target_n), None)
    if target is None:
        raise SystemExit(f"round {target_n} not found in run {run_id}")

    for key in ("ran", "findings", "with_findings", "triage", "resolved"):
        if key in payload:
            target[key] = payload[key]

    save_state(project, run_id, state)

    with_findings = target.get("with_findings", [])
    print(f"run_id={run_id}")
    print(f"round={target_n}")
    print(f"findings={len(target.get('findings', []))}")
    print(f"with_findings={_encode_pairs(with_findings)}")
    print(f"with_findings_count={len(with_findings)}")
    print(f"resolved={target.get('resolved')}")
    return 0


def cmd_circuit_check(args, project: str, project_root: Path, sid: str) -> int:
    run_id = _resolve_run(args, project, sid)
    state = load_state(project, run_id)
    rounds = state.get("rounds", [])
    last_n = rounds[-1]["n"] if rounds else 0
    with_findings = rounds[-1].get("with_findings", []) if rounds else []
    # Fix round-trips completed so far = review rounds beyond the first.
    roundtrips = max(0, last_n - 1)
    at_cap = last_n >= MAX_REVIEW_ROUNDS
    must_fix = len(with_findings)
    # Stop and hand back when the cap is reached and must-fix work remains.
    should_break = at_cap and must_fix > 0

    print(f"run_id={run_id}")
    print(f"last_round={last_n}")
    print(f"max_review_rounds={MAX_REVIEW_ROUNDS}")
    print(f"roundtrips={roundtrips}")
    print(f"at_cap={1 if at_cap else 0}")
    print(f"must_fix_remaining={must_fix}")
    print(f"should_break={1 if should_break else 0}")
    return 0


def cmd_status(args, project: str, project_root: Path, sid: str) -> int:
    run_id = _resolve_run(args, project, sid)
    state = load_state(project, run_id)
    rounds = state.get("rounds", [])
    print(f"run_id={run_id}")
    print(f"status={state.get('status')}")
    print(f"reviewers={','.join(state.get('reviewers', []))}")
    print(f"perspectives={','.join(state.get('perspectives', []))}")
    print(f"rounds={len(rounds)}")
    print(f"state_path={state_path(project, run_id)}")
    for r in rounds:
        n = r["n"]
        print(
            f"round.{n}.ran={_encode_pairs(r.get('ran', []))}"
        )
        print(f"round.{n}.findings={len(r.get('findings', []))}")
        print(
            f"round.{n}.with_findings={_encode_pairs(r.get('with_findings', []))}"
        )
        print(f"round.{n}.resolved={r.get('resolved')}")
    return 0


def cmd_finish(args, project: str, project_root: Path, sid: str) -> int:
    run_id = _resolve_run(args, project, sid)
    state = load_state(project, run_id)
    if args.status not in ("completed", "handed_back"):
        raise SystemExit("finish --status must be 'completed' or 'handed_back'")
    state["status"] = args.status
    state["finished_at"] = _common.now_iso()
    save_state(project, run_id, state)
    # Clear the open pointer so a later run does not resolve to this one.
    marker = open_run_marker(sid)
    if marker.is_file() and read_open_run(sid) == run_id:
        try:
            marker.unlink()
        except OSError:
            pass
    print(f"run_id={run_id}")
    print(f"status={args.status}")
    return 0


# ----------------------------------------------------------------------
# Entry point
# ----------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="review_loop")
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="create a new review run")
    p_init.add_argument("--reviewers", required=True, help="comma-separated reviewer ids")
    p_init.add_argument("--perspectives", required=True, help="comma-separated perspectives")
    p_init.add_argument("--title", default="", help="optional run title (for the run id slug)")
    p_init.set_defaults(func=cmd_init)

    p_start = sub.add_parser("start-round", help="begin a review round, return pairs to run")
    p_start.add_argument("--run", default="", help="run id (defaults to the open run)")
    p_start.set_defaults(func=cmd_start_round)

    p_rec = sub.add_parser("record-round", help="store a round's structured result")
    p_rec.add_argument("--run", default="", help="run id (defaults to the open run)")
    p_rec.add_argument("--json", required=True, help="path to the round JSON payload")
    p_rec.set_defaults(func=cmd_record_round)

    p_cc = sub.add_parser("circuit-check", help="report whether the round cap is reached")
    p_cc.add_argument("--run", default="", help="run id (defaults to the open run)")
    p_cc.set_defaults(func=cmd_circuit_check)

    p_st = sub.add_parser("status", help="summarize the run state")
    p_st.add_argument("--run", default="", help="run id (defaults to the open run)")
    p_st.set_defaults(func=cmd_status)

    p_fin = sub.add_parser("finish", help="mark the run terminal and clear the open pointer")
    p_fin.add_argument("--run", default="", help="run id (defaults to the open run)")
    p_fin.add_argument("--status", required=True, help="completed | handed_back")
    p_fin.set_defaults(func=cmd_finish)

    return parser


def main() -> int:
    args = build_parser().parse_args()
    sid = _common.detect_current_session_id()
    project, project_root = _common.get_project_info(session_id=sid)
    return args.func(args, project, project_root, sid)


if __name__ == "__main__":
    sys.exit(main())
