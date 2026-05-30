import csv
import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from whalefall.archive import load_archive_inputs, load_following_file
from whalefall.review import run_audit


def write_archive(folder: Path) -> tuple[Path, Path]:
    data = folder / "data"
    data.mkdir(parents=True)
    following = data / "following.js"
    followers = data / "follower.js"
    following.write_text(
        "window.YTD.following.part0 = "
        + json.dumps(
            [
                {"following": {"accountId": "1", "userName": "whitelist"}},
                {"following": {"accountId": "2", "userName": "mutual"}},
                {"following": {"accountId": "3", "userName": "active"}},
                {"following": {"accountId": "4", "userName": "inactive"}},
                {"following": {"accountId": "5", "userName": "fetcherr"}},
                {"following": {"accountId": "6", "userName": "noposts"}},
                {"following": {"accountId": "7", "userName": "protected", "protected": True}},
                {"following": {"accountId": "8", "userLink": "https://twitter.com/intent/user?user_id=8"}},
            ]
        )
        + ";",
        encoding="utf-8",
    )
    followers.write_text(
        "window.YTD.follower.part0 = "
        + json.dumps(
            [
                {"follower": {"accountId": "2", "userName": "mutual"}},
                {"follower": {"accountId": "8", "userLink": "https://twitter.com/intent/user?user_id=8"}},
            ]
        )
        + ";",
        encoding="utf-8",
    )
    return following, followers


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def test_parse_archive_payloads_from_folder_and_preserve_id_only(tmp_path):
    write_archive(tmp_path)

    following, followers, meta = load_archive_inputs(tmp_path)

    assert len(following) == 8
    assert any(account.id == "8" and account.username == "" for account in following)
    assert any(account.id == "8" and account.username == "" for account in followers)
    assert meta["following_file"].endswith("following.js")
    assert meta["followers_file"].endswith("follower.js")


def test_parse_archive_payloads_from_zip(tmp_path):
    archive_root = tmp_path / "twitter-archive"
    write_archive(archive_root)
    zip_path = tmp_path / "twitter-archive.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        for path in archive_root.rglob("*"):
            if path.is_file():
                archive.write(path, path.relative_to(tmp_path).as_posix())

    following, followers, meta = load_archive_inputs(zip_path)

    assert len(following) == 8
    assert {account.id for account in followers} == {"2", "8"}
    assert meta["following_file"].endswith("data/following.js")


def test_direct_following_file_can_be_json_accounts(tmp_path):
    following_file = tmp_path / "following.json"
    following_file.write_text(json.dumps({"accounts": [{"id": "123", "username": "direct"}]}), encoding="utf-8")

    accounts = load_following_file(following_file)

    assert len(accounts) == 1
    assert accounts[0].id == "123"
    assert accounts[0].username == "direct"


def test_audit_conservative_review_package_and_comment_only_approval(tmp_path):
    following, followers = write_archive(tmp_path / "archive")
    activity = tmp_path / "activity.json"
    activity.write_text(
        json.dumps(
            {
                "activity": [
                    {"user_id": "1", "username": "whitelist", "last_post_at": "2024-01-01T00:00:00Z", "status": "ok"},
                    {"user_id": "2", "username": "mutual", "last_post_at": "2024-01-01T00:00:00Z", "status": "ok"},
                    {"user_id": "3", "username": "active", "last_post_at": "2026-05-01T00:00:00Z", "status": "ok"},
                    {"user_id": "4", "username": "inactive", "last_post_at": "2024-01-01T00:00:00Z", "status": "ok"},
                    {"user_id": "5", "username": "fetcherr", "status": "error", "error": "429"},
                    {"user_id": "6", "username": "noposts", "status": "no_visible_posts"},
                    {"user_id": "7", "username": "protected", "last_post_at": "2024-01-01T00:00:00Z", "status": "ok"},
                ]
            }
        ),
        encoding="utf-8",
    )
    keep = tmp_path / "keep.txt"
    keep.write_text("@whitelist\n", encoding="utf-8")
    out_dir = tmp_path / "review"

    summary = run_audit(
        following_file=following,
        followers_file=followers,
        activity_files=[activity],
        keep_handles_file=keep,
        threshold_days=180,
        out_dir=out_dir,
        now=datetime(2026, 5, 30, tzinfo=UTC),
    )

    assert summary["brand"] == "Whalefall"
    assert summary["unfollows_executed"] == 0
    assert summary["counts"]["keep_whitelist"] == 1
    assert summary["counts"]["keep_mutual"] == 2
    assert summary["counts"]["keep_active"] == 1
    assert summary["counts"]["unfollow_candidate"] == 1
    assert summary["counts"]["review_error"] == 1
    assert summary["counts"]["review_no_visible_posts"] == 1
    assert summary["counts"]["review_protected"] == 1

    candidates = read_csv(out_dir / "inactive-candidates.csv")
    assert [row["username"] for row in candidates] == ["inactive"]

    manual = {row["username"]: row["recommendation"] for row in read_csv(out_dir / "manual-review.csv")}
    assert manual["fetcherr"] == "review_error"
    assert manual["noposts"] == "review_no_visible_posts"

    protected_rows = {row["username"]: row["recommendation"] for row in read_csv(out_dir / "protected.csv")}
    assert protected_rows["whitelist"] == "keep_whitelist"
    assert protected_rows["mutual"] == "keep_mutual"
    assert protected_rows["protected"] == "review_protected"
    assert protected_rows["id:8"] == "keep_mutual"

    approval_lines = (out_dir / "approved-unfollows.txt").read_text(encoding="utf-8").splitlines()
    handle_lines = [line for line in approval_lines if "@inactive" in line]
    assert handle_lines == ["# @inactive days_inactive=880 last_post=2024-01-01T00:00:00Z"]
    assert all(not line.startswith("@") for line in approval_lines)

    activity_needed = json.loads((out_dir / "activity-needed-following.json").read_text(encoding="utf-8"))
    assert {account["username"] for account in activity_needed["accounts"]} == {"fetcherr", "noposts"}
