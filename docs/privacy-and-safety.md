# Privacy And Safety

Whalefall is designed as a local review tool. The v0.1 package has no code path
that signs in to X, reads browser cookies, sends network requests, or unfollows
accounts.

## Local Files

Inputs are read from paths you provide:

- X archive `.zip` or extracted archive folder
- `following.js` / `following.json`
- `follower.js` / `follower.json`
- JSON or JSONL activity cache
- optional keep-list text file

Outputs are written only under `--out-dir`, or under `whalefall-output/runs/`
when no output directory is supplied.

## Do Not Commit Personal Graph Data

Your X archive and generated review package can reveal private social-graph
information. The project `.gitignore` excludes common archive, cache, and output
names, but you should still check `git status` before committing anything.

## Conservative Scoring

Whalefall only writes `inactive-candidates.csv` rows when a real latest visible
post timestamp exists and is older than the configured threshold.

These cases are not inactive candidates in v0.1:

- keep-list handles
- mutual follows
- protected/private accounts
- fetch errors
- rate limits
- suspended-looking or not-found statuses
- accounts with no visible posts
- accounts with no supplied activity record

## No Mutation

`approved-unfollows.txt` is comment-only. It is a review aid, not an execution
input. v0.1 ships no executor command.
