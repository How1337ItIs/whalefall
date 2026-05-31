import json
import sys
from pathlib import Path

from whalefall.ui import ReviewUiConfig, build_state, execute_selected


def write_candidates(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "id,username,name,days_inactive,last_post_at,reasons,profile_url",
                "1,inactive,Inactive,800,2024-01-01T00:00:00Z,old,https://x.com/inactive",
                "2,older,Older,1200,2023-01-01T00:00:00Z,older,https://x.com/older",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def test_ui_defaults_candidates_checked_and_writes_dry_run_approval(tmp_path):
    review_dir = tmp_path / "review"
    review_dir.mkdir()
    candidate_file = review_dir / "inactive-candidates.csv"
    write_candidates(candidate_file)

    config = ReviewUiConfig(review_dir=review_dir)
    state = build_state(config)

    assert state["total_candidates"] == 2
    assert state["selected_count"] == 2
    assert [row["username"] for row in state["candidates"]] == ["older", "inactive"]

    result = execute_selected(config, ["inactive"])

    assert result["dry_run"] is True
    assert result["would_unfollow"] == 1
    approval = (review_dir / "whalefall-ui-approved-unfollows.txt").read_text(encoding="utf-8")
    assert "@inactive" in approval
    selection = json.loads((review_dir / "whalefall-ui-selection.json").read_text(encoding="utf-8"))
    assert selection["selected_usernames"] == ["inactive"]


def test_ui_per_item_executor_records_successes(tmp_path):
    review_dir = tmp_path / "review"
    review_dir.mkdir()
    write_candidates(review_dir / "inactive-candidates.csv")
    log_path = review_dir / "executed.txt"
    executor = review_dir / "executor.py"
    executor.write_text(
        "import sys\n"
        "from pathlib import Path\n"
        "Path(sys.argv[2]).open('a', encoding='utf-8').write(sys.argv[1] + '\\n')\n",
        encoding="utf-8",
    )

    config = ReviewUiConfig(
        review_dir=review_dir,
        execute_enabled=True,
        execute_command=f"{sys.executable} {executor} {{username}} {log_path}",
        max_actions=10,
    )

    result = execute_selected(config, ["inactive", "older"])

    assert result["ok"] is True
    assert result["attempted"] == 2
    assert log_path.read_text(encoding="utf-8").splitlines() == ["inactive", "older"]
    ledger = (review_dir / "whalefall-unfollow-ledger.jsonl").read_text(encoding="utf-8")
    assert '"username": "inactive"' in ledger
    assert '"status": "ok"' in ledger

    state = build_state(config)
    assert state["already_unfollowed"] == 2
    assert state["selected_count"] == 0
