from __future__ import annotations

import csv
import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from .activity import build_activity_lookup, load_activity_records
from .archive import load_archive_inputs, load_followers_file, load_following_file, normalize_handle
from .models import AccountRecord, ActivityRecord, ScoredAccount
from .scoring import MANUAL_RECOMMENDATIONS, PROTECTED_RECOMMENDATIONS, activity_for_account, account_key, score_accounts
from .timeutil import iso_now, slug_timestamp


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def load_keep_handles(path: Path | None) -> set[str]:
    if not path or not path.exists():
        return set()
    handles: set[str] = set()
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        handles.add(normalize_handle(line.split(",", 1)[0]))
    return handles


def recommendation_counts(scored: list[ScoredAccount]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in scored:
        counts[row.recommendation] = counts.get(row.recommendation, 0) + 1
    return dict(sorted(counts.items()))


def write_scored_csv(path: Path, rows: list[ScoredAccount]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(ScoredAccount.__dataclass_fields__.keys())
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))


def _load_inputs(
    archive: Path | None,
    following_file: Path | None,
    followers_file: Path | None,
) -> tuple[list[AccountRecord], list[AccountRecord], dict[str, Any], list[str]]:
    warnings: list[str] = []
    archive_following: list[AccountRecord] = []
    archive_followers: list[AccountRecord] = []
    meta: dict[str, Any] = {}

    if archive:
        archive_following, archive_followers, archive_meta = load_archive_inputs(archive)
        meta["archive"] = archive_meta

    if following_file:
        following = load_following_file(following_file)
        meta["following_file"] = str(following_file)
    else:
        following = archive_following

    if not following:
        raise ValueError("audit requires --archive or --following-file with at least one followee")

    if followers_file:
        followers = load_followers_file(followers_file)
        meta["followers_file"] = str(followers_file)
    else:
        followers = archive_followers

    if not followers:
        warnings.append("no follower.js/json supplied; mutual protection is unavailable or incomplete")

    return following, followers, meta, warnings


def _activity_needed_accounts(
    accounts: list[AccountRecord],
    scored: list[ScoredAccount],
    activities: dict[str, ActivityRecord],
) -> list[AccountRecord]:
    by_id = {row.id: row for row in scored if row.id}
    by_handle = {normalize_handle(row.username): row for row in scored if row.username and not row.username.startswith("id:")}
    needed: list[AccountRecord] = []
    for account in accounts:
        row = by_id.get(account.id) or by_handle.get(normalize_handle(account.username)) or by_handle.get(account_key(account))
        if not row or row.recommendation not in MANUAL_RECOMMENDATIONS:
            continue
        activity = activity_for_account(account, activities)
        if not activity or row.recommendation in {"review_error", "review_no_visible_posts", "review_activity_needed"}:
            needed.append(account)
    return needed


def _write_approval_template(path: Path, candidates: list[ScoredAccount]) -> None:
    lines = [
        "# Whalefall approval template",
        "# Every generated candidate below is commented out on purpose.",
        "# The local UI writes a separate selected-handles file when execution is explicitly enabled.",
        "# Uncommenting this generated template is not required for the UI.",
        "",
    ]
    if not candidates:
        lines.append("# No inactive candidates were found from the supplied activity data.")
    for row in candidates:
        lines.append(f"# @{row.username} days_inactive={row.days_inactive} last_post={row.last_post_at or 'unknown'}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_review_markdown(
    path: Path,
    scored: list[ScoredAccount],
    counts: dict[str, int],
    threshold_days: int,
    warnings: list[str],
) -> None:
    candidates = [row for row in scored if row.recommendation == "unfollow_candidate"]
    lines = [
        "# Whalefall Review",
        "",
        "> Dead follows sink. Let the living graph breathe.",
        "",
        f"- generated: {iso_now()}",
        "- mode: review-only",
        "- unfollows executed: 0",
        f"- threshold: {threshold_days} days since latest visible post",
        f"- accounts scored: {len(scored)}",
        f"- inactive candidates: {len(candidates)}",
        "",
        "## Counts",
        "",
    ]
    for key, value in counts.items():
        lines.append(f"- {key}: {value}")
    if warnings:
        lines.extend(["", "## Warnings", ""])
        for warning in warnings:
            lines.append(f"- {warning}")
    lines.extend(
        [
            "",
            "## Candidate Rule",
            "",
            "An account only lands in `inactive-candidates.csv` when it has a real latest visible post timestamp older than the threshold.",
            "Errors, protected accounts, missing activity, and no-visible-post profiles stay out of the candidate list.",
            "",
            "## Top Candidates",
            "",
            "| Handle | Days inactive | Last post | Followers | Why |",
            "| --- | ---: | --- | ---: | --- |",
        ]
    )
    for row in candidates[:100]:
        lines.append(
            f"| [@{row.username}]({row.profile_url}) | {row.days_inactive if row.days_inactive is not None else ''} "
            f"| {row.last_post_at or ''} | {row.followers_count} | {row.reasons} |"
        )
    if not candidates:
        lines.append("| | | | | No candidates from supplied activity data. |")
    lines.extend(
        [
            "",
            "## Execution Safety",
            "",
            "`approved-unfollows.txt` is comment-only by default. Use `whalefall ui` to check or uncheck candidates and write a separate selected-handles file.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_audit(
    archive: Path | None = None,
    following_file: Path | None = None,
    followers_file: Path | None = None,
    activity_files: list[Path] | None = None,
    keep_handles_file: Path | None = None,
    threshold_days: int = 180,
    out_dir: Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    following, followers, input_meta, warnings = _load_inputs(archive, following_file, followers_file)
    activity_records: list[ActivityRecord] = []
    for path in activity_files or []:
        activity_records.extend(load_activity_records(path))
    if not activity_records:
        warnings.append("no activity file supplied; archive-only audit cannot identify inactive accounts")

    keep_handles = load_keep_handles(keep_handles_file)
    mutual_handles = {normalize_handle(account.username) for account in followers if account.username}
    mutual_ids = {str(account.id) for account in followers if account.id}
    activities = build_activity_lookup(activity_records)

    scored = score_accounts(
        following,
        activities,
        threshold_days=threshold_days,
        keep_handles=keep_handles,
        mutual_handles=mutual_handles,
        mutual_ids=mutual_ids,
        now=now,
    )

    output_dir = out_dir or (Path.cwd() / "whalefall-output" / "runs" / slug_timestamp(now))
    output_dir.mkdir(parents=True, exist_ok=True)

    candidates = [row for row in scored if row.recommendation == "unfollow_candidate"]
    manual = [row for row in scored if row.recommendation in MANUAL_RECOMMENDATIONS]
    protected = [row for row in scored if row.recommendation in PROTECTED_RECOMMENDATIONS]
    activity_needed = _activity_needed_accounts(following, scored, activities)
    counts = recommendation_counts(scored)

    paths = {
        "summary": output_dir / "summary.json",
        "inactive_candidates": output_dir / "inactive-candidates.csv",
        "manual_review": output_dir / "manual-review.csv",
        "protected": output_dir / "protected.csv",
        "review_markdown": output_dir / "review.md",
        "approved_unfollows": output_dir / "approved-unfollows.txt",
        "activity_needed_following": output_dir / "activity-needed-following.json",
        "scored_json": output_dir / "scored-accounts.json",
        "normalized_following": output_dir / "normalized-following.json",
    }

    write_scored_csv(paths["inactive_candidates"], candidates)
    write_scored_csv(paths["manual_review"], manual)
    write_scored_csv(paths["protected"], protected)
    write_json(paths["scored_json"], {"generated_at": iso_now(), "accounts": [asdict(row) for row in scored]})
    write_json(paths["normalized_following"], {"generated_at": iso_now(), "accounts": [asdict(row) for row in following]})
    write_json(
        paths["activity_needed_following"],
        {
            "generated_at": iso_now(),
            "reason": "unprotected accounts without a usable latest visible post timestamp",
            "accounts": [asdict(row) for row in activity_needed],
        },
    )
    _write_approval_template(paths["approved_unfollows"], candidates)
    _write_review_markdown(paths["review_markdown"], scored, counts, threshold_days, warnings)

    summary = {
        "ok": True,
        "brand": "Whalefall",
        "brand_family": "Midas Whale",
        "mode": "review_only",
        "unfollows_executed": 0,
        "generated_at": iso_now(),
        "run_dir": str(output_dir),
        "threshold_days": threshold_days,
        "accounts": len(following),
        "activity_records": len(activity_records),
        "mutuals_protected": len(mutual_handles | {f"id:{item}" for item in mutual_ids}),
        "keep_handles_protected": len(keep_handles),
        "inactive_candidates": len(candidates),
        "manual_review": len(manual),
        "protected": len(protected),
        "activity_needed": len(activity_needed),
        "counts": counts,
        "inputs": {
            **input_meta,
            "activity_files": [str(path) for path in activity_files or []],
            "keep_handles_file": str(keep_handles_file) if keep_handles_file else "",
        },
        "warnings": warnings,
        "artifacts": {key: str(path) for key, path in paths.items()},
    }
    write_json(paths["summary"], summary)
    return summary
