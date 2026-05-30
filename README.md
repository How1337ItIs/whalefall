# Whalefall

> Dead follows sink. Let the living graph breathe.

Whalefall is a local-first Midas Whale tool for reviewing stale X follows. It
is for people who follow too many accounts, have a noisy feed, or are close to
X's following limits and want a private way to decide what to prune.

It is inspired by the old Untweeps-style idea: find people you follow who have
not posted in a long time. The difference is that Whalefall is deliberately
boring where safety matters. It reads files on your machine, scores
conservatively, writes a review package, and stops. No SaaS upload. No account
delegation. No auto-unfollow command.

The name is the metaphor. A whale fall is what happens when the dead weight
sinks and becomes visible as its own ecosystem. This tool does the same pass
over a noisy follow list: surface the accounts that look truly dormant, protect
the relationships that still matter, and leave every ambiguous case for human
review.

## What This Is For

Use Whalefall when you want to:

- audit a large X following list without handing your account to a third-party
  cleanup service;
- protect mutuals, friends, projects, and private accounts from accidental
  pruning;
- generate CSVs you can inspect before manually unfollowing anything;
- work from your own X archive and local notes instead of paid API access.

Do not use Whalefall expecting:

- one-click bulk unfollowing;
- automatic browser scraping in v0.1;
- magic inactivity detection from an archive alone;
- a hosted dashboard.

Whalefall v0.1 is a review package generator. That is the whole safety model.

## Status And Safety Model

Whalefall v0.1 is review-only.

- No sign-in.
- No browser cookies.
- No paid API requirement.
- No network calls.
- No unfollow command.
- No telemetry.
- No cloud upload.

The generated `approved-unfollows.txt` file is comment-only. It is a planning
aid, not an execution input. v0.1 ships no command that consumes it.

## How It Works

Whalefall combines three local inputs:

1. Your following list, usually from `data/following.js` inside an X archive.
2. Your follower list, usually from `data/follower.js`, so mutuals can be
   protected.
3. Optional activity records with the latest visible post timestamp for accounts
   you follow.

Then it scores each followee:

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

Only `unfollow_candidate` rows are written to `inactive-candidates.csv`.
Errors, missing data, protected accounts, and no-visible-post profiles never
become candidates in v0.1.

## What The X Archive Can And Cannot Tell You

Your X archive is enough to tell Whalefall who you follow and, when
`follower.js` is present, which of those accounts follow you back.

Your X archive usually does not contain every followee's latest post timestamp.
That means an archive-only run is still useful, but it will mostly produce an
`activity-needed-following.json` queue rather than a large inactive-candidate
list.

To identify true inactive candidates, Whalefall needs activity records. You can
create those records manually, from a previous local cache, or from a future
hydration tool. You do not need paid API access if you are willing to build a
small local activity cache yourself.

## Requirements

- Python 3.10 or newer.
- A local X archive, or direct `following.js` / `following.json` input.
- Optional but strongly recommended: `follower.js` / `follower.json` from the
  same X archive.
- Optional: an activity cache JSON/JSONL file containing latest visible post
  timestamps.
- Optional: a keep-list text file.

## Install

Clone the repository, then install from the repo root:

```powershell
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

## Step 1: Download Your X Archive

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

You can pass any of these:

- the full archive `.zip`;
- the extracted archive folder;
- `following.js` directly;
- `following.json` directly.

## Step 2: Prepare A Keep List

Create `keep-handles.txt` with one handle per line:

```text
# one handle per line
favorite-project
close-friend
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

## Step 3: Run An Archive-Only Audit

This is the safest first run:

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

## Step 4: Add Activity Data Without Paid API Access

Activity records tell Whalefall the latest visible post timestamp for a followee.
You can make a small cache by manually checking X profiles and writing JSON.

Create `activity-cache.json`:

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
- `user_id` is optional but strongly useful for matching ID-only archive rows.
- `last_post_at` must be an actual timestamp or parseable date.
- `status: "ok"` plus an old `last_post_at` can become an inactive candidate.
- `status: "error"` never becomes an inactive candidate.
- `status: "no_visible_posts"` never becomes an inactive candidate.
- `status: "protected"` or `status: "private"` goes to protected review.

JSONL also works:

```jsonl
{"username":"active_account","user_id":"1001","last_post_at":"2026-05-01T12:00:00Z","status":"ok"}
{"username":"old_account","user_id":"1002","last_post_at":"2024-01-01T12:00:00Z","status":"ok"}
{"username":"rate_limited_account","user_id":"1003","status":"error","error":"429"}
```

## Step 5: Run With Activity Data

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

## Step 6: Read The Review Package

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

The only list you should consider for manual unfollow review. A row appears here
only when Whalefall has a real latest visible post timestamp older than your
threshold.

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

Comment-only template. In v0.1, this file does not do anything. It exists so you
can copy candidate handles into a manual workflow later.

### `activity-needed-following.json`

Queue of unprotected accounts that need better activity data. This file can be
used as a smaller followee input on a later pass:

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
- rerun against a smaller `activity-needed-following.json` queue;
- wait for a future browser-hydration release.

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

Run tests:

```powershell
python -m pytest -q
```

The test suite uses synthetic X archive fixtures only. No real archive, account,
cookie, or token is needed.

## Privacy Checklist Before Sharing Output

Before sending any Whalefall output to someone else:

- Do not send your raw X archive unless you mean to reveal your follow graph.
- Inspect CSVs for handles you consider sensitive.
- Remove `normalized-following.json` if the recipient only needs summary counts.
- Share `review.md` screenshots rather than raw graph files when possible.
- Delete the output directory when finished.

See [docs/privacy-and-safety.md](docs/privacy-and-safety.md).

## v0.2 Candidates

- Browser-session activity hydration.
- Static HTML review table.
- Better large-account and verified-account guards.
- Optional second-pass verification before any future executor exists.
