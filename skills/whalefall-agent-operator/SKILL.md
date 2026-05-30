---
name: whalefall-agent-operator
description: Supervise a Whalefall local-first X following audit with offline review, optional read-only local activity hydration, cache merge, and human-review safety gates.
always: false
action_class: 1
relevance_keywords:
  - whalefall
  - x archive
  - twitter archive
  - following audit
  - inactive follows
  - unfollow review
  - activity cache
  - local hydration
---

# Whalefall Agent Operator

Use this skill when a user wants a local Whalefall audit of their X following
list. This is a review-only workflow. The agent may help prepare evidence and
artifacts, but it must not unfollow accounts.

## Hard Rules

- Do not execute unfollows.
- Do not add or suggest a hidden mutation step.
- Do not upload the user's raw X archive, generated graph, activity cache, or
  review files to a remote service.
- Do not print, save, or transmit browser cookies, tokens, API keys, or session
  secrets.
- Do not treat fetch errors, rate limits, protected profiles, private profiles,
  no-visible-posts states, deleted-looking profiles, or suspended-looking
  profiles as inactivity.
- Only classify an account as a candidate when the review package has a real
  latest visible post timestamp older than the chosen threshold.
- End with human-readable artifacts and `unfollows_executed: 0`.

## Inputs To Ask For Or Locate

- X archive `.zip` or extracted archive folder.
- `data/following.js` from the X archive.
- `data/follower.js` from the same archive when available.
- Optional `keep-handles.txt`.
- Optional existing activity cache in JSON or JSONL.
- Optional local browser/session access for read-only activity hydration.

## Baseline Offline Audit

Run this first. It proves the archive parses, protects mutuals/keep-list rows,
and creates the activity-needed queue.

```powershell
whalefall audit `
  --archive C:\path\to\twitter-archive.zip `
  --keep-handles C:\path\to\keep-handles.txt `
  --threshold-days 180 `
  --out-dir C:\path\to\whalefall-review
```

If the user does not have a keep list yet, create a small text file with one
handle per line. Use `@handle` or `handle`; both are accepted.

## Agent-Assisted Hydration

The X archive usually does not include each followee's latest post timestamp.
For a useful full audit, supervise a local read-only hydration pass:

1. Read `activity-needed-following.json`.
2. Process a small batch of accounts.
3. Use the user's local browser/session or another explicitly chosen local
   source to inspect latest visible activity.
4. Write normalized activity records only:
   - `username`
   - `user_id` when available
   - `last_post_at` when visible
   - `status`
   - `error` when relevant
5. Stop on repeated errors or rate limits.
6. Cool down before the next batch.
7. Merge the activity file back into the audit.

Accepted activity statuses:

```text
ok
error
no_visible_posts
protected
private
```

Only `ok` with a parseable `last_post_at` can become an inactive candidate.

## Merge And Review

Rerun the audit with one or more activity files:

```powershell
whalefall audit `
  --archive C:\path\to\twitter-archive.zip `
  --activity-file C:\path\to\activity-cache.json `
  --activity-file C:\path\to\activity-cache-extra.jsonl `
  --keep-handles C:\path\to\keep-handles.txt `
  --threshold-days 180 `
  --out-dir C:\path\to\whalefall-review
```

Then verify:

- `summary.json` reports `ok: true`.
- `summary.json` reports `unfollows_executed: 0`.
- `inactive-candidates.csv` contains only rows with old real latest-post
  timestamps.
- `manual-review.csv` contains ambiguous/error/no-visible-post rows.
- `protected.csv` contains keep-list, mutual, protected, and private rows.
- `approved-unfollows.txt` is comment-only and inert.

## Human Handoff

Give the user:

- `review.md`
- `inactive-candidates.csv`
- `manual-review.csv`
- `protected.csv`
- `summary.json`

Explain:

- No accounts were unfollowed.
- `inactive-candidates.csv` is a candidate review list, not an execution list.
- `manual-review.csv` is not an inactive list.
- Protected/private, mutual, keep-list, error, and no-visible-post rows were
  intentionally kept out of candidate status.

## Privacy Check Before Finishing

Search the review/output folder for private material before sharing:

```powershell
rg -n "auth_token|ct0|cookie|secret|token|api_key|password" C:\path\to\whalefall-review
```

If the search finds secrets or local private paths in shareable artifacts, stop
and redact or regenerate the package before sharing.
