from __future__ import annotations

from dataclasses import dataclass


@dataclass
class AccountRecord:
    id: str = ""
    username: str = ""
    name: str = ""
    description: str = ""
    protected: bool | None = None
    verified: bool | None = None
    followers_count: int = 0
    following_count: int = 0
    tweet_count: int = 0
    created_at: str = ""
    source: str = ""


@dataclass
class ActivityRecord:
    username: str = ""
    user_id: str = ""
    last_post_at: str | None = None
    last_post_id: str | None = None
    last_post_text: str | None = None
    fetched_at: str = ""
    status: str = "ok"
    error: str | None = None
    source: str = ""


@dataclass
class ScoredAccount:
    id: str
    username: str
    name: str
    followers_count: int
    following_count: int
    tweet_count: int
    protected: bool | None
    verified: bool | None
    last_post_at: str | None
    last_post_id: str | None
    days_inactive: int | None
    recommendation: str
    reasons: str
    risk_flags: str
    profile_url: str
