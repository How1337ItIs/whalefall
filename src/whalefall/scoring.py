from __future__ import annotations

from datetime import datetime

from .activity import build_activity_lookup
from .archive import normalize_handle
from .models import AccountRecord, ActivityRecord, ScoredAccount
from .timeutil import days_since, parse_datetime, utc_now


PROTECTED_RECOMMENDATIONS = {"keep_whitelist", "keep_mutual", "review_protected"}
MANUAL_RECOMMENDATIONS = {"review_activity_needed", "review_error", "review_no_visible_posts"}


def account_key(account: AccountRecord) -> str:
    handle = normalize_handle(account.username)
    if handle:
        return handle
    if account.id:
        return f"id:{account.id}"
    return ""


def display_username(account: AccountRecord) -> str:
    return normalize_handle(account.username) or (f"id:{account.id}" if account.id else "")


def profile_url_for_account(account: AccountRecord) -> str:
    handle = normalize_handle(account.username)
    if handle:
        return f"https://x.com/{handle}"
    if account.id:
        return f"https://twitter.com/intent/user?user_id={account.id}"
    return ""


def activity_for_account(account: AccountRecord, activities: dict[str, ActivityRecord]) -> ActivityRecord | None:
    handle = normalize_handle(account.username)
    keys = [handle, str(account.id), f"id:{account.id}", account_key(account)]
    for key in keys:
        if key and key in activities:
            return activities[key]
    return None


def score_accounts(
    accounts: list[AccountRecord],
    activity_records: list[ActivityRecord] | dict[str, ActivityRecord],
    threshold_days: int,
    keep_handles: set[str] | None = None,
    mutual_handles: set[str] | None = None,
    mutual_ids: set[str] | None = None,
    now: datetime | None = None,
) -> list[ScoredAccount]:
    now = now or utc_now()
    keep_handles = {normalize_handle(item) for item in (keep_handles or set()) if item}
    mutual_handles = {normalize_handle(item) for item in (mutual_handles or set()) if item}
    mutual_ids = {str(item) for item in (mutual_ids or set()) if item}
    activities = activity_records if isinstance(activity_records, dict) else build_activity_lookup(activity_records)

    scored: list[ScoredAccount] = []
    for account in accounts:
        handle = normalize_handle(account.username)
        activity = activity_for_account(account, activities)
        reasons: list[str] = []
        risk_flags: list[str] = []
        latest = activity.last_post_at if activity else None
        inactive_days = days_since(latest, now=now)

        resolved_username = display_username(account)
        if activity and normalize_handle(activity.username):
            resolved_username = normalize_handle(activity.username)
        resolved_profile_url = f"https://x.com/{resolved_username}" if resolved_username and not resolved_username.startswith("id:") else profile_url_for_account(account)

        keep_key = handle or (f"id:{account.id}" if account.id else "")
        if keep_key in keep_handles or (account.id and f"id:{account.id}" in keep_handles):
            recommendation = "keep_whitelist"
            reasons.append("handle is in keep list")
        elif handle in mutual_handles or (account.id and account.id in mutual_ids):
            recommendation = "keep_mutual"
            reasons.append("account follows you back")
            risk_flags.append("mutual")
        elif account.protected or (activity and activity.status in {"protected", "private"}):
            recommendation = "review_protected"
            reasons.append("protected account; latest activity may be invisible")
            risk_flags.append("protected")
        elif not activity:
            recommendation = "review_activity_needed"
            reasons.append("no activity record supplied")
            risk_flags.append("activity_needed")
        elif activity.status == "error":
            recommendation = "review_error"
            reasons.append(f"activity fetch error: {activity.error or 'unknown'}")
            risk_flags.append("fetch_error")
        elif activity.status in {"no_visible_posts", "empty", "not_found", "suspended"}:
            recommendation = "review_no_visible_posts"
            reasons.append(f"activity status is {activity.status}; do not infer inactivity")
            risk_flags.append("no_visible_posts")
        elif not latest or not parse_datetime(latest):
            recommendation = "review_no_visible_posts"
            reasons.append("no parseable latest visible post timestamp")
            risk_flags.append("no_visible_posts")
        elif inactive_days is not None and inactive_days >= threshold_days:
            recommendation = "unfollow_candidate"
            reasons.append(f"last visible post is {inactive_days} days old")
        else:
            recommendation = "keep_active"
            reasons.append(f"last visible post is {inactive_days} days old")

        if account.verified:
            risk_flags.append("verified")
        if account.followers_count >= 100000:
            risk_flags.append("large_account")

        scored.append(
            ScoredAccount(
                id=account.id,
                username=resolved_username,
                name=account.name,
                followers_count=account.followers_count,
                following_count=account.following_count,
                tweet_count=account.tweet_count,
                protected=account.protected,
                verified=account.verified,
                last_post_at=latest,
                last_post_id=activity.last_post_id if activity else None,
                days_inactive=inactive_days,
                recommendation=recommendation,
                reasons="; ".join(reasons),
                risk_flags="; ".join(dict.fromkeys(risk_flags)),
                profile_url=resolved_profile_url,
            )
        )

    return sorted(
        scored,
        key=lambda row: (
            0 if row.recommendation == "unfollow_candidate" else 1,
            0 if row.recommendation in PROTECTED_RECOMMENDATIONS else 1,
            -(row.days_inactive or -1),
            row.username.lower(),
        ),
    )
