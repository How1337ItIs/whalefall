from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from .archive import normalize_handle
from .models import ActivityRecord
from .timeutil import iso_now, parse_datetime


def activity_from_any(raw: dict[str, Any], source: str = "") -> ActivityRecord:
    username = raw.get("username") or raw.get("userName") or raw.get("screenName") or raw.get("screen_name") or raw.get("handle") or ""
    error = raw.get("error") or raw.get("error_message") or raw.get("errorMessage")
    status = str(raw.get("status") or ("error" if error else "ok")).strip().lower()
    last_post_at = (
        raw.get("last_post_at")
        or raw.get("lastPostAt")
        or raw.get("latest_post_at")
        or raw.get("latestPostAt")
        or raw.get("last_visible_post_at")
        or raw.get("latest_visible_post_at")
        or raw.get("created_at")
    )
    return ActivityRecord(
        username=normalize_handle(str(username)),
        user_id=str(raw.get("user_id") or raw.get("userId") or raw.get("id") or raw.get("accountId") or ""),
        last_post_at=str(last_post_at) if last_post_at else None,
        last_post_id=str(raw.get("last_post_id") or raw.get("lastPostId") or raw.get("tweet_id") or "") or None,
        last_post_text=raw.get("last_post_text") or raw.get("lastPostText") or raw.get("text"),
        fetched_at=str(raw.get("fetched_at") or raw.get("fetchedAt") or iso_now()),
        status=status,
        error=str(error) if error else None,
        source=source,
    )


def load_activity_records(path: Path) -> list[ActivityRecord]:
    if path.suffix.lower() == ".jsonl":
        records: list[ActivityRecord] = []
        for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            payload = json.loads(line)
            if isinstance(payload, dict):
                records.append(activity_from_any(payload, source=f"file:{path}"))
        return records

    payload = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    if isinstance(payload, dict):
        for key in ("activity", "records", "data", "results"):
            if isinstance(payload.get(key), list):
                payload = payload[key]
                break
    if not isinstance(payload, list):
        raise ValueError(f"{path} does not contain a list of activity records")
    return [activity_from_any(item, source=f"file:{path}") for item in payload if isinstance(item, dict)]


def activity_rank(record: ActivityRecord) -> tuple[int, str]:
    if record.last_post_at and parse_datetime(record.last_post_at):
        return (3, record.fetched_at)
    if record.status in {"ok", "no_visible_posts", "protected", "private"}:
        return (2, record.fetched_at)
    if record.status == "error":
        return (1, record.fetched_at)
    return (0, record.fetched_at)


def build_activity_lookup(records: Iterable[ActivityRecord]) -> dict[str, ActivityRecord]:
    lookup: dict[str, ActivityRecord] = {}
    for record in records:
        keys: list[str] = []
        handle = normalize_handle(record.username)
        if handle:
            keys.append(handle)
        if record.user_id:
            keys.extend([str(record.user_id), f"id:{record.user_id}"])
        for key in keys:
            existing = lookup.get(key)
            if existing and activity_rank(existing) > activity_rank(record):
                continue
            lookup[key] = record
    return lookup
