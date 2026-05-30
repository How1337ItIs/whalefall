# Whalefall

> Dead follows sink. Let the living graph breathe.

Whalefall is a local-first audit tool for reviewing stale X follows. It is for
people who follow too many accounts, have a noisy feed, or are close to X's
following limits and want a private way to decide what to prune.

The product has two honest layers:

1. **Standalone offline mode:** the `whalefall audit` CLI reads a local X
   archive, optional follower data, a keep list, and any activity cache you
   already have. It writes a review package and stops.
2. **Agent-assisted full hydration:** in real use, a local AI coding agent or
   operator-supervised automation loop does the slow part: hydrate latest
   visible activity through a local browser/session in batches, compact the
   cache, merge the evidence, regenerate the review package, and enforce safety
   gates. Whalefall does not depend on one model, vendor, or hosted service.

Whalefall is inspired by the old Untweeps-style idea: find people you follow
who have not posted in a long time. The difference is that Whalefall is
deliberately boring where safety matters. It reads files on your machine,
scores conservatively, writes review artifacts, and never unfollows accounts in
v0.1.

## What This Is For

Use Whalefall when you want to:

- audit a large X following list without handing your account to a third-party
  cleanup service;
- protect mutuals, trusted people, projects, communities, and private accounts
  from accidental pruning;
- generate CSVs you can inspect before manually unfollowing anything;
- work from your own X archive and local notes instead of paid API access;
- let a trusted local agent supervise the slow read-only hydration work.

Do not use Whalefall expecting:

- one-click bulk unfollowing;
- a hosted SaaS dashboard;
- default X API spend;
- magic inactivity detection from an archive alone;
- unattended browser automation that mutates your account.

Whalefall v0.1 is a review package generator. Full cheap activity discovery is
realistic, but it is an agent-assisted local workflow around the review package,
not a hosted SaaS or one-click mutation tool.

## Safety Model

Standalone v0.1:

- No sign-in.
- No browser cookies.
- No paid API requirement.
- No network calls.
- No unfollow command.
- No telemetry.
- No cloud upload.

Agent-assisted hydration:

- Uses the user's local browser/session only for read-only activity checks.
- Does not print or upload cookie values.
- Runs in small batches with delays and cooldowns.
- Caches normalized activity evidence, not raw browser secrets.
- Treats `error`, `no_visible_posts`, protected, private, and ambiguous rows as
  manual review.
- Regenerates the review package after each merge.
- Still executes zero unfollows.

The generated `approved-unfollows.txt` file is comment-only. It is a planning
aid, not an execution input. v0.1 ships no command that consumes it.

## How The Workflow Really Works

The X archive provides the graph:

1. Export your X archive.
2. Use `data/following.js` for accounts you follow.
3. Use `data/follower.js` when available so mutuals can be protected.
4. Add a local keep list for trusted people, projects, collaborators, artists,
   communities, and accounts you never want suggested.

The archive usually does **not** contain every followee's latest post timestamp.
That is why standalone archive-only mode mostly produces an
`activity-needed-following.json` queue.

The full workflow adds activity evidence:

1. A local AI coding agent or operator reads the runbook.
2. The agent runs a small read-only browser/session batch over the queue.
3. The batch writes activity records such as `ok`, `error`,
   `no_visible_posts`, `protected`, or `private`.
4. The agent compacts and deduplicates the activity cache.
5. The agent reruns review generation with the archive plus merged cache.
6. Only accounts with a real latest visible post timestamp older than the
   threshold become `unfollow_candidate`.
7. Everything ambiguous stays in manual review.
8. A human reads the artifacts before doing anything in X.

The conservative scoring rule is:

```text
if handle is in keep list:
  keep_whitelist
elif account follows you back:
  keep_mutual
elif account is protected/private:
  review_protected
elif no activity record was supplied:
  review_activity_needed
elif activity fetch errored:
  review_error
elif no visible latest post timestamp exists:
  review_no_visible_posts
elif latest visible post is older than threshold:
  unfollow_candidate
else:
  keep_active
```

`unfollow_candidate` means "worth human review." It does not mean "the tool has
unfollowed this account."

## Install

From this package directory:

```powershell
Set-Location automation\openclaw\tools\whalefall
python -m pip install -e .
```

Confirm the CLI is available:

```powershell
whalefall --version
whalefall audit --help
```

Run without installing:

```powershell
$env:PYTHONPATH = "$PWD\src"
python -m whalefall audit --help
```

macOS/Linux equivalent:

```bash
PYTHONPATH="$PWD/src" python -m whalefall audit --help
```

## Standalone Offline Mode

This mode works today without browser automation. It is safe, private, and
incomplete until you provide activity evidence.

### Step 1: Download Your X Archive

In X:

1. Open Settings.
2. Go to your account data / archive export area.
3. Request an archive.
4. Wait for X to prepare it.
5. Download the archive `.zip`.
6. Keep it local. Do not commit it to git.

Whalefall looks for these files inside the archive:

```text
data/following.js
data/follower.js
```

You can pass the full archive `.zip`, the extracted archive folder,
`following.js` directly, or `following.json` directly.

### Step 2: Prepare A Keep List

Create `keep-handles.txt` with one handle per line:

```text
# one handle per line
favorite-project
trusted-contact
local-venue
```

Rules:

- `@handle` and `handle` both work.
- Blank lines are ignored.
- Lines starting with `#` are ignored.
- Anything in the keep list is protected before activity scoring.

You can start from:

```powershell
Copy-Item examples\keep-handles.example.txt keep-handles.txt
notepad keep-handles.txt
```

### Step 3: Run An Archive-Only Audit

```powershell
whalefall audit `
  --archive C:\path\to\twitter-archive.zip `
  --keep-handles C:\path\to\keep-handles.txt `
  --out-dir C:\path\to\whalefall-review
```

Expected result:

- mutuals are protected if `follower.js` is available;
- keep-list handles are protected;
- unprotected accounts without activity data go to
  `activity-needed-following.json`;
- there may be few or zero inactive candidates.

This is normal. The archive has the graph, not the latest-post state.

### Step 4: Rerun With Activity Data

Activity records tell Whalefall the latest visible post timestamp for a followee.
They can come from manual checks, a previous local cache, or an agent-supervised
local hydration run.

Example `activity-cache.json`:

```json
{
  "activity": [
    {
      "username": "active_account",
      "user_id": "1001",
      "last_post_at": "2026-05-01T12:00:00Z",
      "status": "ok"
    },
    {
      "username": "old_account",
      "user_id": "1002",
      "last_post_at": "2024-01-01T12:00:00Z",
      "status": "ok"
    },
    {
      "username": "rate_limited_account",
      "user_id": "1003",
      "status": "error",
      "error": "429"
    },
    {
      "username": "no_visible_posts_account",
      "user_id": "1004",
      "status": "no_visible_posts"
    }
  ]
}
```

Important details:

- `username` can be with or without `@`.
- `user_id` is optional but useful for matching ID-only archive rows.
- `last_post_at` must be an actual timestamp or parseable date.
- `status: "ok"` plus an old `last_post_at` can become an inactive candidate.
- `status: "error"` never becomes an inactive candidate.
- `status: "no_visible_posts"` never becomes an inactive candidate.
- `status: "protected"` or `status: "private"` goes to protected review.

Run with activity:

```powershell
whalefall audit `
  --archive C:\path\to\twitter-archive.zip `
  --activity-file C:\path\to\activity-cache.json `
  --keep-handles C:\path\to\keep-handles.txt `
  --threshold-days 180 `
  --out-dir C:\path\to\whalefall-review
```

You can pass multiple activity files:

```powershell
whalefall audit `
  --archive C:\path\to\twitter-archive.zip `
  --activity-file C:\path\to\activity-cache-a.json `
  --activity-file C:\path\to\activity-cache-b.jsonl `
  --out-dir C:\path\to\whalefall-review
```

When duplicate activity records exist, Whalefall prefers usable latest-post
records over errors.

## Agent-Assisted Full Hydration

Use this when you want the useful result, not just an archive-only queue. The
workflow stays local-first:

- the user keeps the archive on their machine;
- the user stays signed in locally if browser/session hydration is used;
- a local AI coding agent supervises read-only batches and cache merging;
- no raw archive is uploaded to a SaaS;
- no API spend happens by default;
- no unfollows happen automatically.

The requirement is local supervision and readable artifacts, not a specific
agent, model, vendor, or hosted service.

Whalefall v0.1 does not ship a browser hydrator. The supervised operator loop
is:

```powershell
# Pseudo-command: use a local read-only hydrator or agent script.
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

If you build a custom hydrator, keep machine-specific scripts, run artifacts,
archives, and caches outside any shared package.

See [AGENT_RUNBOOK.md](AGENT_RUNBOOK.md) for the vendor-neutral operator
workflow.

## Agent Skill

For agents, use this vendor-neutral skill:

```text
skills/whalefall-agent-operator/SKILL.md
```

It describes the generic Whalefall workflow without account-specific names,
local run directories, handoffs, or credentials.

## Shared Local Workflow

What the user does:

1. Downloads their X archive.
2. Keeps the archive local.
3. Creates or reviews `keep-handles.txt`.
4. Optionally signs into X in their local browser if they want supervised
   browser/session hydration.
5. Reviews the generated package before manually acting in X.

What the local agent/operator does:

1. Runs `whalefall audit` in archive-only mode first.
2. Reads `activity-needed-following.json`.
3. Hydrates latest visible activity in small read-only batches through the
   user's local browser/session or another explicitly chosen local source.
4. Handles rate limits by stopping, cooling down, and resuming later.
5. Compacts and merges activity evidence.
6. Reruns `whalefall audit` with the merged activity cache.
7. Checks that `unfollows_executed` is `0` and the approval file is comment-only.
8. Hands the review artifacts back to the user.

What the user reviews:

- `review.md` for the summary and top candidates.
- `inactive-candidates.csv` for accounts with old real latest-post timestamps.
- `manual-review.csv` for errors, no-visible-posts, and activity-needed rows.
- `protected.csv` for mutuals, keep-list entries, and protected/private rows.
- `activity-needed-following.json` if they want another hydration pass.
- `approved-unfollows.txt` as an inert planning template only.

What never happens automatically:

- no unfollows;
- no cookie printing;
- no raw archive upload;
- no SaaS processing;
- no default API spend;
- no treating `error` or `no_visible_posts` as inactivity.

## Review Package Artifacts

The audit command writes:

```text
summary.json
inactive-candidates.csv
manual-review.csv
protected.csv
review.md
approved-unfollows.txt
activity-needed-following.json
scored-accounts.json
normalized-following.json
```

### `summary.json`

Machine-readable run summary:

- input paths;
- warning messages;
- recommendation counts;
- output artifact paths;
- `unfollows_executed: 0`.

### `inactive-candidates.csv`

The only list you should consider for manual unfollow review. A row appears
here only when Whalefall has a real latest visible post timestamp older than
your threshold.

### `manual-review.csv`

Ambiguous accounts. Typical reasons:

- no activity record supplied;
- latest post could not be seen;
- fetch error or rate limit;
- no visible posts.

Do not treat this as an inactive list.

### `protected.csv`

Accounts protected by keep list, mutual status, or protected/private status.

### `approved-unfollows.txt`

Comment-only template. In v0.1, this file does not do anything. It exists so
you can copy candidate handles into a manual workflow later.

### `activity-needed-following.json`

Queue of unprotected accounts that need better activity data. This file can be
used as a smaller followee input on a later offline pass:

```powershell
whalefall audit `
  --following-file C:\path\to\whalefall-review\activity-needed-following.json `
  --activity-file C:\path\to\new-activity-cache.json `
  --keep-handles C:\path\to\keep-handles.txt `
  --out-dir C:\path\to\whalefall-review-pass-2
```

## Sample Run

Use the included synthetic sample data:

```powershell
whalefall audit `
  --following-file examples\following.sample.js `
  --followers-file examples\follower.sample.js `
  --activity-file examples\activity-cache.example.json `
  --keep-handles examples\keep-handles.example.txt `
  --out-dir sample-review
```

Then inspect:

```powershell
Get-Content sample-review\review.md
Import-Csv sample-review\inactive-candidates.csv
Import-Csv sample-review\manual-review.csv
Import-Csv sample-review\protected.csv
```

## Privacy And Safety Checklist

Before running:

- Use a local output folder.
- Keep the raw X archive out of git.
- Decide whether local browser/session hydration is acceptable for this audit.
- Set a small batch size if using browser/session hydration.
- Stop on repeated rate limits and cool down.

Before sharing output:

- Do not send your raw X archive unless you mean to reveal your follow graph.
- Inspect CSVs for handles you consider sensitive.
- Remove `normalized-following.json` if the recipient only needs summary
  counts.
- Share `review.md` screenshots rather than raw graph files when possible.
- Delete the output directory when finished.

Never share:

- browser cookies;
- `auth_token`, `ct0`, API keys, or access tokens;
- raw browser storage;
- a full archive unless the recipient should see the follow graph.

See [docs/privacy-and-safety.md](docs/privacy-and-safety.md).

## Troubleshooting

### `could not find data/following.js`

The path passed to `--archive` is not the downloaded X archive `.zip` or the
extracted archive root. Point Whalefall at the zip itself, the extracted folder
that contains `data/`, or use `--following-file` directly.

### `audit requires --archive or --following-file`

Pass one of:

```powershell
whalefall audit --archive C:\path\to\twitter-archive.zip
whalefall audit --archive C:\path\to\extracted-twitter-archive
whalefall audit --following-file C:\path\to\following.js
```

### `archive-only audit cannot identify inactive accounts`

This is expected when no `--activity-file` is supplied. X archives contain your
follow graph but not every followee's latest post timestamp. Whalefall will
still normalize the graph and write `activity-needed-following.json`.

### Too many `review_activity_needed` rows

That means Whalefall needs activity data before it can classify those accounts.
Options:

- create a small manual `activity-cache.json` for the accounts you care about;
- ask a local agent/operator to run the supervised hydration workflow;
- rerun against a smaller `activity-needed-following.json` queue.

### Mutuals are not protected

Make sure `follower.js` was included. If you pass direct files, include:

```powershell
--followers-file C:\path\to\follower.js
```

If your X archive does not include follower data, Whalefall cannot know who
follows you back.

### A protected/private account is not in `inactive-candidates.csv`

Correct. Protected/private accounts are intentionally held out of candidate
lists because Whalefall cannot reliably see their latest activity.

### The approval file is all comments

Correct. v0.1 is review-only. The approval file is intentionally inert.

### Windows says `whalefall` is not recognized

Either install the package:

```powershell
python -m pip install -e .
```

Or run the module directly:

```powershell
$env:PYTHONPATH = "$PWD\src"
python -m whalefall audit --help
```

## Testing

Install test tooling if needed:

```powershell
python -m pip install pytest
```

Run tests from the Whalefall package directory:

```powershell
python -m pytest -q
```

The test suite uses synthetic X archive fixtures only. No real archive,
account, cookie, or token is needed.

## v0.2 Candidates

- First-class agent-assisted hydration command or wrapper.
- Static HTML review table.
- Better large-account and verified-account guards.
- Optional second-pass verification before any future executor exists.
- Desktop wrapper after the local review path is proven with early users.
