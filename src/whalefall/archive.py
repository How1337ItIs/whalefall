from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .models import AccountRecord


def normalize_handle(handle: str | None) -> str:
    return str(handle or "").strip().lstrip("@").lower()


def _to_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _to_bool(value: Any) -> bool | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"true", "1", "yes"}:
        return True
    if text in {"false", "0", "no"}:
        return False
    return None


def _metrics(raw: dict[str, Any]) -> dict[str, Any]:
    metrics = raw.get("public_metrics") or raw.get("publicMetrics") or {}
    return metrics if isinstance(metrics, dict) else {}


def _id_from_user_link(value: str | None) -> str:
    if not value:
        return ""
    query = parse_qs(urlparse(str(value)).query)
    for key in ("user_id", "userId", "id"):
        if query.get(key):
            return str(query[key][0])
    return ""


def _handle_from_user_link(value: str | None) -> str:
    if not value:
        return ""
    parsed = urlparse(str(value))
    host = parsed.netloc.lower()
    if not (host.endswith("twitter.com") or host.endswith("x.com")):
        return ""
    parts = [part for part in parsed.path.split("/") if part]
    if not parts or parts[0] in {"intent", "i"}:
        return ""
    return normalize_handle(parts[0])


def account_from_any(raw: dict[str, Any], source: str = "") -> AccountRecord:
    metrics = _metrics(raw)
    user_link = str(raw.get("userLink") or raw.get("url") or raw.get("profileUrl") or "")
    username = (
        raw.get("username")
        or raw.get("userName")
        or raw.get("screenName")
        or raw.get("screen_name")
        or raw.get("handle")
        or _handle_from_user_link(user_link)
        or ""
    )
    account_id = (
        raw.get("id")
        or raw.get("id_str")
        or raw.get("user_id")
        or raw.get("userId")
        or raw.get("accountId")
        or _id_from_user_link(user_link)
        or ""
    )
    return AccountRecord(
        id=str(account_id),
        username=normalize_handle(str(username)),
        name=str(raw.get("name") or raw.get("displayName") or ""),
        description=str(raw.get("description") or raw.get("bio") or user_link or ""),
        protected=_to_bool(raw.get("protected") if "protected" in raw else raw.get("isProtected")),
        verified=_to_bool(raw.get("verified") if "verified" in raw else raw.get("isVerified")),
        followers_count=_to_int(metrics.get("followers_count") or metrics.get("followers") or raw.get("followers_count")),
        following_count=_to_int(metrics.get("following_count") or metrics.get("following") or raw.get("friends_count")),
        tweet_count=_to_int(metrics.get("tweet_count") or metrics.get("tweets") or raw.get("statuses_count")),
        created_at=str(raw.get("created_at") or raw.get("createdAt") or ""),
        source=source,
    )


def extract_js_assigned_json(text: str) -> Any:
    stripped = text.strip().lstrip("\ufeff")
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass

    match = re.search(r"=\s*(\[.*\]|\{.*\})\s*;?\s*$", stripped, flags=re.S)
    if match:
        return json.loads(match.group(1))

    start = stripped.find("[")
    end = stripped.rfind("]")
    if start < 0 or end < start:
        start = stripped.find("{")
        end = stripped.rfind("}")
    if start < 0 or end < start:
        raise ValueError("could not find JSON payload in archive file")
    return json.loads(stripped[start : end + 1])


def accounts_from_payload(payload: Any, archive_keys: tuple[str, ...], source: str) -> list[AccountRecord]:
    if isinstance(payload, dict):
        for key in ("accounts", "data", "following", "followers"):
            if isinstance(payload.get(key), list):
                payload = payload[key]
                break
    if not isinstance(payload, list):
        raise ValueError(f"{source} does not contain an account array")

    accounts: list[AccountRecord] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        raw = item
        for key in archive_keys:
            if isinstance(item.get(key), dict):
                raw = item[key]
                break
        account = account_from_any(raw, source=source)
        if account.id or account.username:
            accounts.append(account)
    return accounts


def parse_account_text(text: str, archive_keys: tuple[str, ...], source: str) -> list[AccountRecord]:
    return accounts_from_payload(extract_js_assigned_json(text), archive_keys=archive_keys, source=source)


def load_following_file(path: Path) -> list[AccountRecord]:
    return parse_account_text(path.read_text(encoding="utf-8", errors="replace"), ("following",), f"file:{path}")


def load_followers_file(path: Path) -> list[AccountRecord]:
    return parse_account_text(path.read_text(encoding="utf-8", errors="replace"), ("follower",), f"file:{path}")


def find_archive_data_file(root: Path, name: str) -> Path:
    direct = [root / "data" / name, root / name]
    for path in direct:
        if path.exists():
            return path
    candidates = sorted(root.rglob(name), key=lambda item: (item.parent.name != "data", len(item.parts), str(item)))
    if not candidates:
        raise FileNotFoundError(f"could not find {name} under {root}")
    return candidates[0]


def _zip_member(names: list[str], name: str) -> str | None:
    normalized = [item.replace("\\", "/") for item in names]
    preferred = [item for item in normalized if item.endswith(f"/data/{name}")]
    if preferred:
        return sorted(preferred, key=len)[0]
    matches = [item for item in normalized if item.endswith(f"/{name}") or item == name]
    return sorted(matches, key=len)[0] if matches else None


def _read_zip_text(zip_path: Path, member: str) -> str:
    with zipfile.ZipFile(zip_path) as archive:
        with archive.open(member) as handle:
            return handle.read().decode("utf-8", errors="replace")


def load_archive_inputs(archive_path: Path) -> tuple[list[AccountRecord], list[AccountRecord], dict[str, Any]]:
    if archive_path.is_dir():
        following_path = find_archive_data_file(archive_path, "following.js")
        try:
            followers_path = find_archive_data_file(archive_path, "follower.js")
        except FileNotFoundError:
            followers_path = None
        followers = load_followers_file(followers_path) if followers_path else []
        return (
            load_following_file(following_path),
            followers,
            {
                "archive": str(archive_path),
                "following_file": str(following_path),
                "followers_file": str(followers_path) if followers_path else "",
            },
        )

    if zipfile.is_zipfile(archive_path):
        with zipfile.ZipFile(archive_path) as archive:
            names = archive.namelist()
        following_member = _zip_member(names, "following.js")
        if not following_member:
            raise FileNotFoundError(f"could not find data/following.js in {archive_path}")
        follower_member = _zip_member(names, "follower.js")
        following = parse_account_text(_read_zip_text(archive_path, following_member), ("following",), f"zip:{archive_path}!{following_member}")
        followers = (
            parse_account_text(_read_zip_text(archive_path, follower_member), ("follower",), f"zip:{archive_path}!{follower_member}")
            if follower_member
            else []
        )
        return (
            following,
            followers,
            {
                "archive": str(archive_path),
                "following_file": following_member,
                "followers_file": follower_member or "",
            },
        )

    raise ValueError(f"{archive_path} is neither an archive .zip nor a folder")
