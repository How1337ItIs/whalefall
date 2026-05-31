from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .review import run_audit
from .ui import ReviewUiConfig, serve_review_ui


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="whalefall",
        description="Whalefall: local-first X following audit and review UI from Midas Whale.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    audit = sub.add_parser("audit", help="Build a review package from an X archive or following file")
    audit.add_argument("--archive", type=Path, help="Path to X archive .zip or extracted archive folder")
    audit.add_argument("--following-file", type=Path, help="Path to following.js/json")
    audit.add_argument("--followers-file", type=Path, help="Path to follower.js/json for mutual protection")
    audit.add_argument("--activity-file", type=Path, action="append", help="JSON/JSONL activity cache/results; may be repeated")
    audit.add_argument("--keep-handles", type=Path, help="Text file with one protected handle per line")
    audit.add_argument("--threshold-days", type=int, default=180, help="Candidate threshold in days; default: 180")
    audit.add_argument("--out-dir", type=Path, help="Directory for review package files")
    audit.set_defaults(func=command_audit)

    ui = sub.add_parser("ui", help="Open a local checkbox review UI for a Whalefall review directory")
    ui.add_argument("--review-dir", type=Path, required=True, help="Directory containing inactive-candidates.csv")
    ui.add_argument("--candidates-file", type=Path, help="Candidate CSV; defaults to inactive-candidates.csv in review dir")
    ui.add_argument("--host", default="127.0.0.1")
    ui.add_argument("--port", type=int, default=8765)
    ui.add_argument("--max-actions", type=int, default=1000)
    ui.add_argument("--sleep-min", type=float, default=0.0)
    ui.add_argument("--sleep-max", type=float, default=0.0)
    ui.add_argument("--enable-execute", action="store_true", help="Enable the Unfollow checked button")
    ui.add_argument(
        "--execute-command",
        help="Local command template. Per-item placeholders: {username}, {id}, {profile_url}. Batch placeholders: {approved_file}, {review_dir}, {count}.",
    )
    ui.add_argument("--execute-mode", choices=["per-item", "batch"], default="per-item")
    ui.add_argument("--open-browser", action="store_true")
    ui.set_defaults(func=command_ui)
    return parser


def command_audit(args: argparse.Namespace) -> int:
    summary = run_audit(
        archive=args.archive,
        following_file=args.following_file,
        followers_file=args.followers_file,
        activity_files=args.activity_file or [],
        keep_handles_file=args.keep_handles,
        threshold_days=args.threshold_days,
        out_dir=args.out_dir,
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


def command_ui(args: argparse.Namespace) -> int:
    if args.enable_execute and not args.execute_command:
        raise ValueError("--enable-execute requires --execute-command")
    serve_review_ui(
        ReviewUiConfig(
            review_dir=args.review_dir,
            candidate_file=args.candidates_file,
            host=args.host,
            port=args.port,
            max_actions=args.max_actions,
            sleep_min=args.sleep_min,
            sleep_max=args.sleep_max,
            execute_enabled=args.enable_execute,
            execute_command=args.execute_command or "",
            execute_mode=args.execute_mode,
            open_browser=args.open_browser,
        )
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
