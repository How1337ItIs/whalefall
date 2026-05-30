from __future__ import annotations

import email.utils
from datetime import UTC, datetime


def utc_now() -> datetime:
    return datetime.now(UTC)


def iso_now() -> str:
    return utc_now().replace(microsecond=0).isoformat().replace("+00:00", "Z")


def slug_timestamp(now: datetime | None = None) -> str:
    return (now or utc_now()).strftime("%Y%m%d-%H%M%S")


def parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    except ValueError:
        pass
    try:
        parsed = email.utils.parsedate_to_datetime(str(value))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    except (TypeError, ValueError):
        return None


def days_since(value: str | None, now: datetime | None = None) -> int | None:
    parsed = parse_datetime(value)
    if not parsed:
        return None
    now = now or utc_now()
    return max(0, int((now - parsed).total_seconds() // 86400))
