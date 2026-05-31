from __future__ import annotations

import csv
import json
import os
import random
import subprocess
import threading
import time
import webbrowser
from dataclasses import dataclass
from datetime import UTC, datetime
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def normalize_handle(value: str) -> str:
    return (value or "").strip().lstrip("@").lower()


def shell_quote(value: str | Path | int | float) -> str:
    text = str(value)
    if os.name == "nt":
        return subprocess.list2cmdline([text])
    import shlex

    return shlex.quote(text)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def candidate_sort_key(row: dict[str, Any]) -> tuple[int, str]:
    try:
        days = int(row.get("days_inactive") or 0)
    except (TypeError, ValueError):
        days = 0
    return (-days, normalize_handle(str(row.get("username") or row.get("handle") or "")))


def read_candidates(path: Path) -> list[dict[str, Any]]:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        username = normalize_handle(str(row.get("username") or row.get("handle") or row.get("screenName") or ""))
        if not username or username in seen:
            continue
        seen.add(username)
        item = dict(row)
        item["username"] = username
        item["profile_url"] = item.get("profile_url") or f"https://x.com/{username}"
        candidates.append(item)
    candidates.sort(key=candidate_sort_key)
    return candidates


def discover_candidates_file(review_dir: Path) -> Path:
    for name in ("inactive-candidates.csv", "unfollow-candidates.csv"):
        path = review_dir / name
        if path.exists():
            return path
    raise FileNotFoundError(f"no inactive-candidates.csv or unfollow-candidates.csv found in {review_dir}")


def ledger_successes(path: Path) -> set[str]:
    if not path.exists():
        return set()
    handles: set[str] = set()
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not raw.strip():
            continue
        try:
            item = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if item.get("status") in {"ok", "submitted"} and item.get("action") in {"unfollow", "batch_unfollow"}:
            username = normalize_handle(str(item.get("username") or ""))
            if username:
                handles.add(username)
    return handles


def write_approval_file(path: Path, usernames: list[str]) -> None:
    lines = [
        "# Whalefall selected unfollows",
        f"# generated: {utc_now()}",
        "# One selected handle per line.",
        "",
    ]
    lines.extend(f"@{username}" for username in usernames)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


@dataclass
class ReviewUiConfig:
    review_dir: Path
    candidate_file: Path | None = None
    selection_file: Path | None = None
    approval_file: Path | None = None
    ledger_file: Path | None = None
    status_file: Path | None = None
    host: str = "127.0.0.1"
    port: int = 8765
    title: str = "Whalefall Review"
    execute_enabled: bool = False
    execute_command: str = ""
    execute_mode: str = "per-item"
    max_actions: int = 1000
    sleep_min: float = 0.0
    sleep_max: float = 0.0
    open_browser: bool = False

    def resolved_candidate_file(self) -> Path:
        return self.candidate_file or discover_candidates_file(self.review_dir)

    def resolved_selection_file(self) -> Path:
        return self.selection_file or (self.review_dir / "whalefall-ui-selection.json")

    def resolved_approval_file(self) -> Path:
        return self.approval_file or (self.review_dir / "whalefall-ui-approved-unfollows.txt")

    def resolved_ledger_file(self) -> Path:
        return self.ledger_file or (self.review_dir / "whalefall-unfollow-ledger.jsonl")

    def resolved_status_file(self) -> Path:
        return self.status_file or (self.review_dir / "whalefall-ui-status.json")


def load_selection(path: Path, default_usernames: list[str]) -> set[str]:
    if not path.exists():
        return set(default_usernames)
    payload = read_json(path)
    selected = payload.get("selected_usernames") if isinstance(payload, dict) else payload
    if not isinstance(selected, list):
        return set(default_usernames)
    return {normalize_handle(str(item)) for item in selected if normalize_handle(str(item))}


def save_selection(path: Path, usernames: list[str]) -> None:
    write_json(
        path,
        {
            "updated_at": utc_now(),
            "selected_usernames": sorted({normalize_handle(item) for item in usernames if normalize_handle(item)}),
        },
    )


def parse_utc(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def read_execution_status(config: ReviewUiConfig) -> dict[str, Any] | None:
    path = config.resolved_status_file()
    if not path.exists():
        return None
    try:
        payload = read_json(path)
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def write_execution_status(config: ReviewUiConfig, payload: dict[str, Any]) -> dict[str, Any]:
    payload = {**payload, "updated_at": utc_now(), "status_file": str(config.resolved_status_file())}
    write_json(config.resolved_status_file(), payload)
    return payload


def is_active_status(status: dict[str, Any] | None) -> bool:
    return bool(status and status.get("state") in {"pending", "running"})


def ledger_summary_for_status(config: ReviewUiConfig, status: dict[str, Any]) -> dict[str, int]:
    started = parse_utc(str(status.get("started_at") or ""))
    selected = {normalize_handle(str(item)) for item in status.get("selected_usernames", []) if normalize_handle(str(item))}
    counts = {"attempted": 0, "ok": 0, "error": 0, "pending": 0}
    if not started or not selected:
        return counts
    ledger = config.resolved_ledger_file()
    if not ledger.exists():
        return counts
    for raw in ledger.read_text(encoding="utf-8", errors="replace").splitlines():
        if not raw.strip():
            continue
        try:
            entry = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if entry.get("action") != "unfollow":
            continue
        username = normalize_handle(str(entry.get("username") or ""))
        if username not in selected:
            continue
        attempted_at = parse_utc(str(entry.get("attempted_at") or ""))
        if attempted_at and attempted_at < started:
            continue
        counts["attempted"] += 1
        state = str(entry.get("status") or "pending")
        if state == "ok":
            counts["ok"] += 1
        elif state == "error":
            counts["error"] += 1
        else:
            counts["pending"] += 1
    return counts


def enrich_execution_status(config: ReviewUiConfig, status: dict[str, Any] | None) -> dict[str, Any] | None:
    if not status:
        return None
    enriched = dict(status)
    enriched["ledger_summary"] = ledger_summary_for_status(config, status)
    return enriched


def build_state(config: ReviewUiConfig) -> dict[str, Any]:
    candidate_file = config.resolved_candidate_file()
    candidates = read_candidates(candidate_file)
    already_unfollowed = ledger_successes(config.resolved_ledger_file())
    selectable = [row["username"] for row in candidates if row["username"] not in already_unfollowed]
    selected = load_selection(config.resolved_selection_file(), selectable)
    for row in candidates:
        username = row["username"]
        row["checked"] = username in selected and username not in already_unfollowed
        row["already_unfollowed"] = username in already_unfollowed

    buckets = {
        "5y_plus": 0,
        "3_to_5y": 0,
        "2_to_3y": 0,
        "1_to_2y": 0,
        "180_to_365d": 0,
    }
    for row in candidates:
        try:
            days = int(row.get("days_inactive") or 0)
        except (TypeError, ValueError):
            days = 0
        if days >= 1825:
            buckets["5y_plus"] += 1
        elif days >= 1095:
            buckets["3_to_5y"] += 1
        elif days >= 730:
            buckets["2_to_3y"] += 1
        elif days >= 365:
            buckets["1_to_2y"] += 1
        else:
            buckets["180_to_365d"] += 1

    return {
        "ok": True,
        "title": config.title,
        "review_dir": str(config.review_dir),
        "candidate_file": str(candidate_file),
        "selection_file": str(config.resolved_selection_file()),
        "approval_file": str(config.resolved_approval_file()),
        "ledger_file": str(config.resolved_ledger_file()),
        "status_file": str(config.resolved_status_file()),
        "execute_enabled": config.execute_enabled,
        "execute_mode": config.execute_mode,
        "max_actions": config.max_actions,
        "execution_status": enrich_execution_status(config, read_execution_status(config)),
        "total_candidates": len(candidates),
        "selected_count": sum(1 for row in candidates if row["checked"]),
        "already_unfollowed": len(already_unfollowed),
        "buckets": buckets,
        "candidates": candidates,
    }


def validate_selected(candidates: list[dict[str, Any]], usernames: list[str], already: set[str]) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    by_handle = {row["username"]: row for row in candidates}
    selected: list[dict[str, Any]] = []
    blocked: list[dict[str, str]] = []
    for raw in usernames:
        username = normalize_handle(str(raw))
        if not username:
            continue
        row = by_handle.get(username)
        if not row:
            blocked.append({"username": username, "reason": "not in candidate file"})
            continue
        if username in already:
            blocked.append({"username": username, "reason": "already marked unfollowed in ledger"})
            continue
        selected.append(row)
    return selected, blocked


def format_command(template: str, mapping: dict[str, str | int | float | Path]) -> str:
    safe_mapping = {key: shell_quote(value) for key, value in mapping.items()}
    return template.format_map(safe_mapping)


def run_command(command: str, cwd: Path) -> dict[str, Any]:
    started = time.time()
    completed = subprocess.run(command, shell=True, cwd=str(cwd), capture_output=True, text=True)
    return {
        "command": command,
        "exit_code": completed.returncode,
        "status": "ok" if completed.returncode == 0 else "error",
        "duration_seconds": round(time.time() - started, 3),
        "stdout_tail": (completed.stdout or "")[-4000:],
        "stderr_tail": (completed.stderr or "")[-4000:],
    }


def execute_selected(config: ReviewUiConfig, usernames: list[str]) -> dict[str, Any]:
    candidates = read_candidates(config.resolved_candidate_file())
    already = ledger_successes(config.resolved_ledger_file())
    selected, blocked = validate_selected(candidates, usernames, already)
    if config.max_actions > 0:
        overflow = selected[config.max_actions :]
        selected = selected[: config.max_actions]
        blocked.extend({"username": row["username"], "reason": "beyond max actions"} for row in overflow)

    selected_usernames = [row["username"] for row in selected]
    save_selection(config.resolved_selection_file(), selected_usernames)
    write_approval_file(config.resolved_approval_file(), selected_usernames)

    if not config.execute_enabled:
        return {
            "ok": True,
            "dry_run": True,
            "would_unfollow": len(selected),
            "selected": selected_usernames,
            "blocked": blocked,
            "approval_file": str(config.resolved_approval_file()),
        }
    if not config.execute_command:
        raise ValueError("execution is enabled but no execute command was configured")
    if config.execute_mode not in {"per-item", "batch"}:
        raise ValueError("execute_mode must be per-item or batch")

    results: list[dict[str, Any]] = []
    if config.execute_mode == "batch":
        command = format_command(
            config.execute_command,
            {
                "approved_file": config.resolved_approval_file(),
                "review_dir": config.review_dir,
                "count": len(selected),
            },
        )
        result = run_command(command, config.review_dir)
        append_jsonl(
            config.resolved_ledger_file(),
            {
                "action": "ui_batch_command",
                "attempted_at": utc_now(),
                "status": result["status"],
                "selected_count": len(selected),
                "command_exit_code": result["exit_code"],
            },
        )
        results.append(result)
    else:
        for index, row in enumerate(selected, 1):
            command = format_command(
                config.execute_command,
                {
                    "username": row["username"],
                    "id": row.get("id") or "",
                    "profile_url": row.get("profile_url") or f"https://x.com/{row['username']}",
                    "review_dir": config.review_dir,
                    "approved_file": config.resolved_approval_file(),
                    "count": len(selected),
                },
            )
            result = run_command(command, config.review_dir)
            append_jsonl(
                config.resolved_ledger_file(),
                {
                    "action": "unfollow",
                    "username": row["username"],
                    "target_user_id": row.get("id") or "",
                    "attempted_at": utc_now(),
                    "status": result["status"],
                    "command_exit_code": result["exit_code"],
                },
            )
            results.append({"username": row["username"], **result})
            if index < len(selected) and config.sleep_max > 0:
                time.sleep(random.uniform(max(0, config.sleep_min), max(config.sleep_min, config.sleep_max)))

    return {
        "ok": not any(item.get("status") == "error" for item in results),
        "dry_run": False,
        "attempted": len(selected),
        "blocked": blocked,
        "results": results,
        "approval_file": str(config.resolved_approval_file()),
        "ledger_file": str(config.resolved_ledger_file()),
    }


def start_execute_job(config: ReviewUiConfig, usernames: list[str]) -> dict[str, Any]:
    current = read_execution_status(config)
    if is_active_status(current):
        return {
            "ok": False,
            "error": "an unfollow job is already pending or running",
            "execution_status": enrich_execution_status(config, current),
        }

    candidates = read_candidates(config.resolved_candidate_file())
    already = ledger_successes(config.resolved_ledger_file())
    selected, blocked = validate_selected(candidates, usernames, already)
    if config.max_actions > 0:
        overflow = selected[config.max_actions :]
        selected = selected[: config.max_actions]
        blocked.extend({"username": row["username"], "reason": "beyond max actions"} for row in overflow)
    selected_usernames = [row["username"] for row in selected]
    save_selection(config.resolved_selection_file(), selected_usernames)
    write_approval_file(config.resolved_approval_file(), selected_usernames)

    base_status = {
        "job_id": str(int(time.time() * 1000)),
        "state": "dry_run" if not config.execute_enabled else "pending",
        "started_at": utc_now(),
        "selected_count": len(selected_usernames),
        "selected_usernames": selected_usernames,
        "blocked": blocked,
        "approval_file": str(config.resolved_approval_file()),
        "ledger_file": str(config.resolved_ledger_file()),
        "execute_enabled": config.execute_enabled,
        "execute_mode": config.execute_mode,
        "message": "dry run wrote selected handles" if not config.execute_enabled else "queued local unfollow command",
    }
    write_execution_status(config, base_status)

    if not config.execute_enabled:
        return {
            "ok": True,
            "started": False,
            "dry_run": True,
            "would_unfollow": len(selected_usernames),
            "approval_file": str(config.resolved_approval_file()),
            "execution_status": enrich_execution_status(config, base_status),
        }

    def worker() -> None:
        running = write_execution_status(
            config,
            {
                **base_status,
                "state": "running",
                "message": "running local unfollow command",
            },
        )
        try:
            result = execute_selected(config, selected_usernames)
            ok = bool(result.get("ok"))
            write_execution_status(
                config,
                {
                    **running,
                    "state": "success" if ok else "failed",
                    "finished_at": utc_now(),
                    "message": "unfollow command completed" if ok else "unfollow command failed",
                    "result": result,
                },
            )
        except Exception as exc:
            write_execution_status(
                config,
                {
                    **running,
                    "state": "failed",
                    "finished_at": utc_now(),
                    "message": "unfollow command crashed",
                    "error": str(exc),
                },
            )

    threading.Thread(target=worker, daemon=True).start()
    return {"ok": True, "started": True, "execution_status": enrich_execution_status(config, base_status)}


HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Whalefall Review</title>
  <style>
    :root {
      color-scheme: light;
      --ink: #182026;
      --muted: #5d6871;
      --line: #d9e0e5;
      --bg: #f6f8f7;
      --panel: #ffffff;
      --sea: #0f766e;
      --gold: #b7791f;
      --bad: #a73434;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: var(--bg);
      color: var(--ink);
      letter-spacing: 0;
    }
    header {
      position: sticky;
      top: 0;
      z-index: 5;
      background: rgba(246, 248, 247, 0.97);
      border-bottom: 1px solid var(--line);
    }
    .bar {
      max-width: 1280px;
      margin: 0 auto;
      padding: 14px 18px;
      display: grid;
      grid-template-columns: minmax(200px, 1fr) auto;
      gap: 12px;
      align-items: center;
    }
    .brand {
      display: flex;
      gap: 12px;
      align-items: center;
      min-width: 0;
    }
    .mark {
      width: 38px;
      height: 38px;
      border: 2px solid var(--sea);
      display: grid;
      place-items: center;
      color: var(--sea);
      font-weight: 800;
      flex: 0 0 auto;
    }
    h1 {
      font-size: 20px;
      margin: 0;
      line-height: 1.1;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .sub {
      color: var(--muted);
      font-size: 12px;
      margin-top: 4px;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .actions {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      justify-content: end;
    }
    button, input, select {
      font: inherit;
    }
    button {
      border: 1px solid var(--line);
      background: var(--panel);
      color: var(--ink);
      min-height: 36px;
      padding: 0 12px;
      cursor: pointer;
      border-radius: 6px;
    }
    button:hover { border-color: var(--sea); }
    button.primary {
      background: var(--sea);
      border-color: var(--sea);
      color: white;
      font-weight: 700;
    }
    button.danger {
      background: var(--bad);
      border-color: var(--bad);
      color: white;
      font-weight: 700;
    }
    button:disabled {
      opacity: .55;
      cursor: not-allowed;
    }
    main {
      max-width: 1280px;
      margin: 0 auto;
      padding: 16px 18px 32px;
    }
    .stats {
      display: grid;
      grid-template-columns: repeat(6, minmax(110px, 1fr));
      gap: 8px;
      margin-bottom: 12px;
    }
    .stat {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 10px;
      min-height: 68px;
    }
    .stat b { display: block; font-size: 20px; }
    .stat span { color: var(--muted); font-size: 12px; }
    .filters {
      display: grid;
      grid-template-columns: minmax(180px, 1fr) 160px 150px;
      gap: 8px;
      margin-bottom: 12px;
    }
    input[type="search"], select {
      min-height: 38px;
      padding: 0 10px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: var(--panel);
      color: var(--ink);
      width: 100%;
    }
    .table-wrap {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      overflow: auto;
      max-height: calc(100vh - 245px);
    }
    table {
      width: 100%;
      border-collapse: collapse;
      min-width: 900px;
    }
    th, td {
      padding: 9px 10px;
      border-bottom: 1px solid var(--line);
      vertical-align: top;
      text-align: left;
      font-size: 13px;
    }
    th {
      position: sticky;
      top: 0;
      z-index: 2;
      background: #eef3f2;
      color: #2d373d;
      font-size: 12px;
      text-transform: uppercase;
    }
    td.check { width: 48px; text-align: center; }
    td.days { width: 110px; font-weight: 700; color: var(--gold); }
    td.last { width: 230px; color: var(--muted); }
    td.handle { width: 220px; font-weight: 700; }
    a { color: var(--sea); text-decoration: none; }
    a:hover { text-decoration: underline; }
    .reason { color: var(--muted); }
    .muted { color: var(--muted); }
    .status {
      margin: 12px 0 0;
      min-height: 22px;
      color: var(--muted);
      font-size: 13px;
      white-space: pre-wrap;
    }
    .pill {
      display: inline-flex;
      align-items: center;
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 2px 8px;
      color: var(--muted);
      font-size: 12px;
      margin-left: 6px;
    }
    @media (max-width: 860px) {
      .bar { grid-template-columns: 1fr; }
      .actions { justify-content: start; }
      .stats { grid-template-columns: repeat(2, minmax(110px, 1fr)); }
      .filters { grid-template-columns: 1fr; }
      .table-wrap { max-height: none; }
    }
  </style>
</head>
<body>
  <header>
    <div class="bar">
      <div class="brand">
        <div class="mark">WF</div>
        <div>
          <h1 id="title">Whalefall Review</h1>
          <div class="sub" id="subtitle">Loading review package</div>
        </div>
      </div>
      <div class="actions">
        <button id="checkVisible">Check visible</button>
        <button id="uncheckVisible">Uncheck visible</button>
        <button id="saveSelection">Save selection</button>
        <button id="execute" class="danger">Unfollow checked</button>
      </div>
    </div>
  </header>
  <main>
    <section class="stats">
      <div class="stat"><b id="total">0</b><span>Total candidates</span></div>
      <div class="stat"><b id="selected">0</b><span>Checked</span></div>
      <div class="stat"><b id="fivey">0</b><span>5y plus</span></div>
      <div class="stat"><b id="threey">0</b><span>3-5y</span></div>
      <div class="stat"><b id="twoy">0</b><span>2-3y</span></div>
      <div class="stat"><b id="oney">0</b><span>1-2y</span></div>
    </section>
    <section class="filters">
      <input id="search" type="search" placeholder="Search handle, name, reason">
      <select id="bucket">
        <option value="all">All ages</option>
        <option value="1825">5y plus</option>
        <option value="1095">3y plus</option>
        <option value="730">2y plus</option>
        <option value="365">1y plus</option>
      </select>
      <select id="checkedFilter">
        <option value="all">All rows</option>
        <option value="checked">Checked only</option>
        <option value="unchecked">Unchecked only</option>
      </select>
    </section>
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th></th>
            <th>Handle</th>
            <th>Days</th>
            <th>Last visible post</th>
            <th>Reason</th>
          </tr>
        </thead>
        <tbody id="rows"></tbody>
      </table>
    </div>
    <div class="status" id="status"></div>
  </main>
  <script>
    let state = null;
    let rows = [];
    let pollTimer = null;
    const selected = new Set();

    function days(row) {
      const parsed = parseInt(row.days_inactive || '0', 10);
      return Number.isFinite(parsed) ? parsed : 0;
    }

    function setStatus(text) {
      document.getElementById('status').textContent = text || '';
    }

    function statusText(status) {
      if (!status) return '';
      const summary = status.ledger_summary || {};
      const pieces = [];
      if (status.state === 'pending') pieces.push(`Pending: ${status.selected_count || 0} checked handles queued.`);
      else if (status.state === 'running') pieces.push(`Running: ${summary.attempted || 0}/${status.selected_count || 0} attempted, ${summary.ok || 0} ok, ${summary.error || 0} failed.`);
      else if (status.state === 'success') pieces.push(`Success: command finished. ${summary.ok || 0} ok, ${summary.error || 0} failed.`);
      else if (status.state === 'failed') pieces.push(`Failed: ${status.message || 'command failed'}. ${summary.ok || 0} ok, ${summary.error || 0} failed.`);
      else if (status.state === 'dry_run') pieces.push(`Dry run: ${status.selected_count || 0} checked handles written to approval file.`);
      else pieces.push(`${status.state || 'Status'}: ${status.message || ''}`);
      if (status.approval_file) pieces.push(`Approval file: ${status.approval_file}`);
      if (status.error) pieces.push(`Error: ${status.error}`);
      return pieces.join('\n');
    }

    function renderExecutionStatus(status) {
      const text = statusText(status);
      if (text) setStatus(text);
    }

    function activeStatus() {
      const status = state && state.execution_status;
      return !!status && (status.state === 'pending' || status.state === 'running');
    }

    function updateCounts() {
      const active = activeStatus();
      document.getElementById('selected').textContent = selected.size;
      document.getElementById('execute').textContent = state.execute_enabled
        ? `Unfollow checked (${selected.size})`
        : `Preview checked (${selected.size})`;
      document.getElementById('execute').disabled = active;
    }

    function visibleRows() {
      const query = document.getElementById('search').value.trim().toLowerCase();
      const bucket = document.getElementById('bucket').value;
      const checkedFilter = document.getElementById('checkedFilter').value;
      const minDays = bucket === 'all' ? 0 : parseInt(bucket, 10);
      return rows.filter((row) => {
        const haystack = `${row.username || ''} ${row.name || ''} ${row.reasons || ''}`.toLowerCase();
        if (query && !haystack.includes(query)) return false;
        if (days(row) < minDays) return false;
        if (checkedFilter === 'checked' && !selected.has(row.username)) return false;
        if (checkedFilter === 'unchecked' && selected.has(row.username)) return false;
        return true;
      });
    }

    function render() {
      const body = document.getElementById('rows');
      body.innerHTML = '';
      for (const row of visibleRows()) {
        const tr = document.createElement('tr');
        const disabled = row.already_unfollowed ? 'disabled' : '';
        const checked = selected.has(row.username) && !row.already_unfollowed ? 'checked' : '';
        tr.innerHTML = `
          <td class="check"><input type="checkbox" data-handle="${row.username}" ${checked} ${disabled}></td>
          <td class="handle"><a href="${row.profile_url}" target="_blank" rel="noreferrer">@${row.username}</a>${row.already_unfollowed ? '<span class="pill">done</span>' : ''}<div class="muted">${row.name || ''}</div></td>
          <td class="days">${row.days_inactive || ''}</td>
          <td class="last">${row.last_post_at || ''}</td>
          <td class="reason">${row.reasons || ''}</td>
        `;
        body.appendChild(tr);
      }
      body.querySelectorAll('input[type="checkbox"]').forEach((box) => {
        box.addEventListener('change', (event) => {
          const handle = event.target.dataset.handle;
          if (event.target.checked) selected.add(handle);
          else selected.delete(handle);
          updateCounts();
        });
      });
      updateCounts();
    }

    async function postJson(path, payload) {
      const response = await fetch(path, {
        method: 'POST',
        headers: {'content-type': 'application/json'},
        body: JSON.stringify(payload),
      });
      const data = await response.json();
      if (!response.ok || data.ok === false) {
        throw new Error(data.error || response.statusText);
      }
      return data;
    }

    async function load() {
      const response = await fetch('/api/state');
      state = await response.json();
      rows = state.candidates || [];
      selected.clear();
      for (const row of rows) {
        if (row.checked) selected.add(row.username);
      }
      document.getElementById('title').textContent = state.title || 'Whalefall Review';
      document.getElementById('subtitle').textContent = state.execute_enabled
        ? `${state.total_candidates} candidates from ${state.candidate_file}`
        : `${state.total_candidates} candidates, execution disabled`;
      document.getElementById('total').textContent = state.total_candidates;
      document.getElementById('fivey').textContent = state.buckets['5y_plus'] || 0;
      document.getElementById('threey').textContent = state.buckets['3_to_5y'] || 0;
      document.getElementById('twoy').textContent = state.buckets['2_to_3y'] || 0;
      document.getElementById('oney').textContent = state.buckets['1_to_2y'] || 0;
      render();
      renderExecutionStatus(state.execution_status);
      if (activeStatus()) startPolling();
    }

    async function pollStatus() {
      try {
        const response = await fetch('/api/status');
        const data = await response.json();
        state.execution_status = data.execution_status;
        renderExecutionStatus(state.execution_status);
        if (activeStatus()) {
          pollTimer = setTimeout(pollStatus, 2500);
        } else {
          await load();
        }
      } catch (error) {
        setStatus(`Status error: ${error.message}`);
      }
    }

    function startPolling() {
      if (pollTimer) return;
      pollTimer = setTimeout(async function tick() {
        pollTimer = null;
        await pollStatus();
      }, 1000);
    }

    document.getElementById('search').addEventListener('input', render);
    document.getElementById('bucket').addEventListener('change', render);
    document.getElementById('checkedFilter').addEventListener('change', render);
    document.getElementById('checkVisible').addEventListener('click', () => {
      for (const row of visibleRows()) {
        if (!row.already_unfollowed) selected.add(row.username);
      }
      render();
    });
    document.getElementById('uncheckVisible').addEventListener('click', () => {
      for (const row of visibleRows()) selected.delete(row.username);
      render();
    });
    document.getElementById('saveSelection').addEventListener('click', async () => {
      setStatus('Saving selection...');
      const data = await postJson('/api/selection', {usernames: Array.from(selected)});
      setStatus(`Saved ${data.selected_count} checked handles to ${data.selection_file}`);
    });
    document.getElementById('execute').addEventListener('click', async () => {
      setStatus(state.execute_enabled ? 'Pending: starting selected unfollows...' : 'Writing dry-run approval file...');
      document.getElementById('execute').disabled = true;
      try {
        const data = await postJson('/api/execute', {usernames: Array.from(selected)});
        state.execution_status = data.execution_status || null;
        renderExecutionStatus(state.execution_status);
        if (state.execution_status && (state.execution_status.state === 'pending' || state.execution_status.state === 'running')) {
          startPolling();
        } else {
          await load();
        }
      } catch (error) {
        setStatus(`Error: ${error.message}`);
      } finally {
        updateCounts();
      }
    });

    load().catch((error) => setStatus(`Error: ${error.message}`));
  </script>
</body>
</html>
"""


def response(handler: BaseHTTPRequestHandler, status: int, body: bytes, content_type: str) -> None:
    handler.send_response(status)
    handler.send_header("content-type", content_type)
    handler.send_header("content-length", str(len(body)))
    handler.send_header("cache-control", "no-store")
    handler.end_headers()
    handler.wfile.write(body)


def json_response(handler: BaseHTTPRequestHandler, status: int, payload: dict[str, Any]) -> None:
    response(handler, status, json.dumps(payload, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")


def make_handler(config: ReviewUiConfig) -> type[BaseHTTPRequestHandler]:
    class ReviewHandler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
            return

        def do_GET(self) -> None:
            path = urlparse(self.path).path
            try:
                if path == "/":
                    response(self, 200, HTML.encode("utf-8"), "text/html; charset=utf-8")
                elif path == "/api/state":
                    json_response(self, 200, build_state(config))
                elif path == "/api/status":
                    json_response(self, 200, {"ok": True, "execution_status": enrich_execution_status(config, read_execution_status(config))})
                else:
                    json_response(self, 404, {"ok": False, "error": "not found"})
            except Exception as exc:
                json_response(self, 500, {"ok": False, "error": str(exc)})

        def do_POST(self) -> None:
            path = urlparse(self.path).path
            try:
                length = int(self.headers.get("content-length", "0"))
                payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
                usernames = payload.get("usernames") or []
                if not isinstance(usernames, list):
                    raise ValueError("usernames must be a list")
                if path == "/api/selection":
                    normalized = sorted({normalize_handle(str(item)) for item in usernames if normalize_handle(str(item))})
                    save_selection(config.resolved_selection_file(), normalized)
                    json_response(
                        self,
                        200,
                        {
                            "ok": True,
                            "selected_count": len(normalized),
                            "selection_file": str(config.resolved_selection_file()),
                        },
                    )
                elif path == "/api/execute":
                    result = start_execute_job(config, [str(item) for item in usernames])
                    json_response(self, 202 if result.get("started") else 200, result)
                else:
                    json_response(self, 404, {"ok": False, "error": "not found"})
            except Exception as exc:
                json_response(self, 500, {"ok": False, "error": str(exc)})

    return ReviewHandler


def serve_review_ui(config: ReviewUiConfig) -> str:
    config.review_dir = config.review_dir.resolve()
    if config.candidate_file:
        config.candidate_file = config.candidate_file.resolve()
    else:
        config.candidate_file = discover_candidates_file(config.review_dir).resolve()
    config.review_dir.mkdir(parents=True, exist_ok=True)
    build_state(config)
    server = ThreadingHTTPServer((config.host, config.port), make_handler(config))
    url = f"http://{config.host}:{server.server_port}/"
    print(json.dumps({"ok": True, "url": url, "candidate_file": str(config.candidate_file), "execute_enabled": config.execute_enabled}, indent=2))
    if config.open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return url
