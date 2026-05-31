---
name: whalefall-release-maintainer
description: Maintain a public Whalefall release or fork safely: sync only public source/docs/examples/tests, run tests and privacy checks, update release docs, and publish without leaking local X archives, cookies, activity caches, or generated review packages.
always: false
action_class: 1
relevance_keywords:
  - whalefall release
  - publish whalefall
  - github release
  - public repo
  - package whalefall
  - release maintainer
  - privacy scan
---

# Whalefall Release Maintainer

Use this skill when maintaining a public Whalefall release, fork, or repository.
It is public-safe and intentionally generic.

## Boundary

Whalefall public repos should contain:

- source code under `src/whalefall/`;
- package metadata;
- docs and runbooks;
- synthetic examples;
- tests using synthetic fixtures;
- public-safe agent skills.

They should not contain:

- a user's raw X archive;
- generated review packages;
- activity caches from real accounts;
- browser cookies or tokens;
- local browser storage;
- local machine paths;
- account-specific candidate lists;
- hidden unfollow executors.

## Standard Release Check

From the package root:

```powershell
python -m pytest -q
python -m compileall -q src
$env:PYTHONPATH = "$PWD\src"
python -m whalefall --help
python -m whalefall audit --help
python -m pip wheel . --no-deps -w dist-smoke
Remove-Item -Recurse -Force dist-smoke
```

Privacy scan:

```powershell
rg -n "auth_token\\s*[:=]|ct0\\s*[:=]|api[_-]?key\\s*[:=]|secret\\s*[:=]|password\\s*[:=]" .
rg -n "twitter-archive|activity-cache.*\\.jsonl|whalefall-review|approved-unfollows\\.txt" .
```

Docs may warn users not to share cookies or tokens. They must not contain real
cookie values, token assignments, raw account exports, or generated review data.

## Git Discipline

Before committing:

```powershell
git status --short --untracked-files=all
git diff --name-status
git diff --check
```

After staging:

```powershell
git diff --cached --name-status
git diff --cached --stat
git diff --cached --check
```

Only commit public release files. If generated outputs appear, remove them and
tighten `.gitignore`.

## Public Counterpart Rule

If a private operator workflow discovers a generally useful bug fix, add the
generic version here or in `whalefall-agent-operator`. Keep the fix useful for
other users without naming private accounts, paths, run IDs, or maintainers.

## Handoff

A release handoff should include:

- commit hash;
- remote URL;
- test commands and results;
- privacy scan result;
- what changed;
- anything intentionally excluded.
