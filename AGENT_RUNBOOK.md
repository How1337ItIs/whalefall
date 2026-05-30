# Whalefall Agent Runbook

This runbook is for a local AI coding agent or human operator supervising a
Whalefall-style follow audit. It is vendor-neutral: the important parts are
local supervision, read-only hydration, cache merging, and human review.

Whalefall v0.1 itself is an offline review CLI. The realistic full result comes
from this supervised workflow around it.

## Non-Negotiables

- Do not run any unfollow executor.
- Do not add an unfollow command to user-facing docs.
- Do not print cookie values, tokens, API keys, `auth_token`, or `ct0`.
- Do not upload raw archives or activity caches to a SaaS.
- Do not treat `error`, `no_visible_posts`, protected, private, suspended, or
  not-found rows as inactive candidates.
- Do not reuse another user's run directory or activity cache unless they
  explicitly provide it for this audit.
- Keep batch sizes small and respect cooldowns after rate limits.
- End with a review package and `unfollows_executed: 0`.

## Inputs

Minimum:

- X archive `.zip` or extracted archive folder with `data/following.js`.
- `keep-handles.txt`.

Strongly recommended:

- `data/follower.js` from the same archive for mutual protection.

Optional:

- Existing `activity-cache.json` or JSONL records.
- Local signed-in browser/session for read-only activity hydration.
- Prior run directory with `activity-needed-following.json`.

## Phase 1: Offline Baseline

Run the review package without activity first:

```powershell
whalefall audit `
  --archive C:\path\to\twitter-archive.zip `
  --keep-handles C:\path\to\keep-handles.txt `
  --threshold-days 180 `
  --out-dir C:\path\to\whalefall-review
```

Check:

- `summary.json` exists.
- `summary.json.unfollows_executed` is `0`.
- `activity-needed-following.json` exists.
- Mutuals and keep-list rows are in `protected.csv`.
- The candidate count may be zero because no activity cache exists yet.

## Phase 2: Read-Only Hydration

Hydrate activity in small batches through a local source. The product
requirement is the pattern, not a specific tool:

1. Read `activity-needed-following.json`.
2. Visit or query a small batch of profiles using the user's local session.
3. Record only normalized evidence:
   - `username`
   - `user_id` when available
   - `last_post_at` when visible
   - `status`
   - `error` when relevant
4. Stop on repeated rate limits.
5. Cool down before resuming.
6. Never mutate the account.

Safe activity statuses:

```text
ok
error
no_visible_posts
protected
private
```

Only `ok` with a parseable `last_post_at` can later become an inactive
candidate. Everything else is manual/protected review.

## Phase 3: Cache Merge

Merge activity records into one cache. Prefer usable latest-post records over
errors and avoid duplicating old batch output.

The standalone package can consume JSON or JSONL activity files:

```powershell
whalefall audit `
  --archive C:\path\to\twitter-archive.zip `
  --activity-file C:\path\to\activity-cache.json `
  --keep-handles C:\path\to\keep-handles.txt `
  --threshold-days 180 `
  --out-dir C:\path\to\whalefall-review
```

Repeat with additional `--activity-file` arguments when needed.

## Phase 4: Review Regeneration

After each hydration batch:

1. Rerun `whalefall audit` with the merged cache.
2. Confirm the latest package is full-scope, not only a narrowed retry queue.
3. Confirm `inactive-candidates.csv` contains only rows with real old
   latest-post timestamps.
4. Confirm `manual-review.csv` contains ambiguous rows.
5. Confirm `approved-unfollows.txt` is comment-only.
6. Hand artifacts to the human reviewer.

## Operator Loop Shape

The public v0.1 package does not ship a browser hydrator. A local agent or
operator can still supervise the same workflow with a read-only local hydrator
or custom script:

```powershell
# Pseudo-command: adapter name is local to the operator's machine.
local-agent-hydrate `
  --following-file C:\path\to\whalefall-review\activity-needed-following.json `
  --out C:\path\to\activity-cache-batch.jsonl `
  --batch-size 20 `
  --read-only

whalefall audit `
  --archive C:\path\to\twitter-archive.zip `
  --activity-file C:\path\to\activity-cache-batch.jsonl `
  --keep-handles C:\path\to\keep-handles.txt `
  --threshold-days 180 `
  --out-dir C:\path\to\whalefall-review
```

Keep machine-specific scripts, handoffs, raw archives, and activity caches out
of shared packages and bug reports. For agents, use this skill:

```text
skills/whalefall-agent-operator/SKILL.md
```

## Human Handoff

Give the human:

- `review.md`
- `inactive-candidates.csv`
- `manual-review.csv`
- `protected.csv`
- `summary.json`

Tell them plainly:

- `inactive-candidates.csv` is the only candidate list.
- It is still a review list, not an execution list.
- `manual-review.csv` is not an inactive list.
- Protected/private and mutual accounts were intentionally held out.
- Nothing was unfollowed.

## Completion Checklist

- `summary.json.ok` is `true`.
- `summary.json.unfollows_executed` is `0`.
- `approved-unfollows.txt` contains only comments.
- Candidate rows have parseable old latest-post timestamps.
- Errors and no-visible-post rows are in manual review.
- Raw archive and browser secrets stayed local.
