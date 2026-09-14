---
name: release
description: Cut and ship a pyaprilaire release — draft a release candidate (rc) off develop, iterate rc's as needed, and then finalize and publish the real version. Use this whenever the user asks to "start a release", "cut a new version", "prepare a draft release", "make an rc", "bump the version", "release X.Y.Z", or "run/finish/publish the release". Covers the full lifecycle: release branch, PR to main, bumpver version bumps, git tags, and GitHub draft/published releases.
---

# Release pyaprilaire

This repo ships releases through a `release/X.Y.Z` branch cut from `develop`, which
goes through one or more **release candidates (rc)** before becoming the real
version. Two phases, each started explicitly by the user:

- **Prepare draft release** — start a new release, or cut another rc for one already
  in progress. Repeatable and safe.
- **Run release** — finalize the version, merge to `main`, and publish. This is the
  public step.

Every GitHub operation goes through `./.claude/skills/release/release.sh`, which uses
the REST API directly (no `gh` CLI, so it runs in agent sandboxes as well as on a
laptop). Run `release.sh --help` for the full list. Every mutating subcommand takes
`--dry-run`, which prints the request instead of sending it — use it whenever you
want to read an action back to the user before taking it.

**Prerequisites:** `bumpver` (via `pip install -e .[dev]`), plus `curl`, `jq`,
`python3` and `git`. Authentication comes from `GH_TOKEN` or `GITHUB_TOKEN` (or the
`gh` CLI's token if it happens to be installed). Work from a clean tree — check
`git status` before touching branches.

## The one irreversible step

`publish` is the only command that cannot be undone. Publishing a GitHub release
fires `.github/workflows/python-publish.yml`, which uploads to **real PyPI**, and
PyPI filenames are immutable — a bad upload burns that version number permanently.

Everything else is reversible. In particular, a **draft** release fires nothing at
all, so a draft can be rewritten as many times as it takes.

So every release — rc's included — follows the same three beats:

1. `release-upsert … --draft` to write the notes,
2. read the notes back to the user and get an explicit go-ahead,
3. `publish` as its own separate action.

Never fold step 3 into step 1. Never publish notes the user has not seen.

Release candidates publish to real PyPI too, marked as a GitHub prerelease. That is
deliberate and safe: `pip install pyaprilaire` will not resolve a PEP 440
pre-release, so `0.10.0rc0` reaches only people who ask for it by version or with
`--pre` — which is exactly what an rc is for.

## Why the version math is simple

`pyproject.toml` configures `[tool.bumpver]` with `commit = true`, `tag = true` and
`push = false`, so each `bumpver update` makes the version-bump commit *and* the
matching tag locally, and pushing stays an explicit separate step.

- `bumpver update --set-version X.Y.Zrc0` — start a brand-new release at rc0.
- `bumpver update --tag rc --tag-num` — bump rc0 → rc1 → rc2 on the current branch.
- `bumpver update --tag final` — strip the rc suffix, leaving plain `X.Y.Z`.

bumpver reads the current version from `pyproject.toml` and from existing VCS tags,
so you never compute a version or tag name by hand.

## Release notes

Notes have four parts, assembled by `release.sh notes`:

1. **A narrative paragraph** — the only part you write. One paragraph of prose, no
   bullets: what this release does for someone using the library, grouped by theme
   rather than restating PR titles in order. Read the PR list first, and
   `release.sh` output aside, check a PR's body when its title alone does not explain
   the "why". No filler like "various improvements".
2. **`## Breaking changes`** — detected automatically, omitted when there are none.
3. **`## What's Changed`** — the PR list.
4. **The full-changelog compare link.**

Write the narrative to a file and pass it with `--narrative`; everything else is
generated:

```bash
./.claude/skills/release/release.sh notes \
  --tag <tag being released> \
  --target <branch or ref being released> \
  --since <boundary ref> \
  --narrative /tmp/narrative.md > /tmp/release-notes.md
```

### Scoping: what `--since` should be

`--since` is the "since when" for both the PR list and the compare link. Pick it
deliberately every time — `release.sh status` reports the right value for each case:

| Notes for | `--since` |
|---|---|
| rc0 | the last **final** release tag |
| rc1 and later | the **previous rc tag of this same release** — so the notes are that rc's delta |
| The final `X.Y.Z` | the last **final** release tag — never one of this release's own rc tags |
| The release PR body | the last **final** release tag (cumulative; refresh it each rc) |

The rc releases are per-rc deltas; the PR body is the cumulative view of the whole
release. That difference is the point — don't reuse one file for both.

### Breaking changes are best-effort — always confirm them

Detection scans each commit's **full message**, subject and body, for a Conventional
Commits `!` marker or a `BREAKING CHANGE:` footer, and quotes the footer text
verbatim as the migration note. Do not paraphrase it.

It cannot be complete, and you must not present it as though it were. The signals
live in squash commit bodies, which can be edited at merge time; and a PR whose
*title* omits the `!` shows up in `## What's Changed` looking ordinary. (PR #79 is
the live example: a real breaking change whose PR title carries no marker.) So when
you read the draft back to the user, ask them to confirm the breaking-changes
section specifically — including whether anything is missing.

If breaking changes are detected, confirm the target version reflects them before
bumping.

## Phase 1: Prepare draft release

### Step 0 — where are we?

Ask for the target version if the user has not given one (plain `MAJOR.MINOR.PATCH`;
you add the rc suffix). Then:

```bash
./.claude/skills/release/release.sh status X.Y.Z
```

`branch_exists: no` → a **new release**, starting at rc0.
`branch_exists: yes` → **another rc**; bumpver derives the number from existing tags.

The output also gives you `last_final_release`, `latest_rc_tag`, the open PR, and the
`notes_since` values to use below. Read its warnings: if it reports that the range
includes already-shipped work, use the `--since <sha>` it suggests rather than the
tag (see "A note on releases before 0.10.0").

### Step A — create or update the release branch

New release:

```bash
git fetch origin develop main
git checkout -b release/X.Y.Z origin/develop
git push -u origin release/X.Y.Z
```

Another rc — bring develop in first, since the point of a new rc is usually to pick
up fixes that have landed since the last one:

```bash
git checkout release/X.Y.Z
git pull origin release/X.Y.Z
git merge origin/develop --no-edit
git push origin release/X.Y.Z
```

If that merge conflicts, stop and resolve it with the user rather than guessing —
these are real conflicts between develop and an in-flight release.

### Step B — bump the version

New release (rc0):

```bash
bumpver update --set-version X.Y.Zrc0
```

Another rc:

```bash
bumpver update --tag rc --tag-num
```

Then push the branch and the tag bumpver just made (its exact name is in bumpver's
output):

```bash
git push origin release/X.Y.Z
git push origin X.Y.Zrc<N>
```

### Step C — refresh the release PR

The PR body should always read as the changelog for the release *as it stands*, which
makes it a running preview of what will ship. Build cumulative notes (`--since` the
last final release tag) and upsert — the same command whether or not the PR exists:

```bash
./.claude/skills/release/release.sh notes --tag release/X.Y.Z --target release/X.Y.Z \
  --since <last final tag> --narrative /tmp/narrative.md > /tmp/pr-body.md
./.claude/skills/release/release.sh pr-upsert X.Y.Z --body-file /tmp/pr-body.md
```

Fill in the repo's PR template (`.github/pull_request_template.md`) around the
changelog rather than discarding it — put the changelog in the summary section.

### Step D — draft the rc release, confirm, publish

Build this rc's **delta** notes (`--since` the previous rc tag, or the last final tag
for rc0 — note this is a different scope from Step C, so rebuild rather than reusing
that file), then draft:

```bash
./.claude/skills/release/release.sh release-upsert X.Y.Zrc<N> \
  --target release/X.Y.Z --notes-file /tmp/rc-notes.md --prerelease --draft
```

Read the notes back to the user, confirm the breaking-changes section with them, then
and only then:

```bash
./.claude/skills/release/release.sh publish X.Y.Zrc<N>
./.claude/skills/release/release.sh workflow-status
```

Report the PR link and the release link. That is the deliverable for this phase.

## Phase 2: Run release

Only start once the user confirms the release is ready to ship.

### Step A — strip the rc suffix

```bash
git checkout release/X.Y.Z
git pull origin release/X.Y.Z
bumpver update --tag final
git push origin release/X.Y.Z
```

This leaves the plain `X.Y.Z` version on the branch plus a local `X.Y.Z` tag. Do not
push that tag yet — push it after the merge, so its commit is verified to be in
`main`'s history.

### Step B — merge to main, with a merge commit

Confirm with the user first. Then:

```bash
./.claude/skills/release/release.sh merge X.Y.Z
```

**This must never be a squash merge**, which is why it goes through the script.
Squashing creates a brand-new commit on `main`: the bumpver tag is left pointing at a
commit outside `main`'s history, and the release branch's own commits stay outside
the tag's ancestry — which silently corrupts *every future release's* changelog, as
each one then reports work that shipped releases ago.

If the script refuses because merge commits are disabled repo-wide, that is a real
blocker, not something to work around by squashing: it needs Settings → General →
Pull Requests → "Allow merge commits". Enabling it does not affect `develop`, whose
ruleset pins merge methods to squash independently.

If the merge fails for any other reason (required checks, conflicts), surface it to
the user rather than forcing it through.

### Step C — push the tag and draft the release

```bash
git fetch origin main
git push origin X.Y.Z
./.claude/skills/release/release.sh notes --tag X.Y.Z --target main \
  --since <last final tag> --narrative /tmp/narrative.md > /tmp/release-notes.md
./.claude/skills/release/release.sh release-upsert X.Y.Z --target main \
  --notes-file /tmp/release-notes.md --draft
```

Scope these to the **previous final release**, not to this release's last rc — the
final notes summarize the whole release, not the last delta.

### Step D — confirm, then publish

Read the draft back to the user (or point them at its URL), confirm they want it
live, then:

```bash
./.claude/skills/release/release.sh publish X.Y.Z
./.claude/skills/release/release.sh workflow-status
```

This is not a prerelease, so the upload goes to real PyPI as the version people get.
Report the published release URL and confirm the workflow run looks healthy.

### Step E — merge main back into develop

```bash
git checkout develop
git pull origin develop
git merge origin/main --no-edit
git push origin develop
```

This carries the version bump back to `develop` and keeps the release tag in its
ancestry, so the next release branch starts from the right version. It is the repo's
existing practice — don't skip it.

## A note on releases before 0.10.0

Releases up to 0.9.1 were squash-merged into `main`, so their tags do not contain the
release branch's commits. A range scoped to one of those tags therefore reports work
that already shipped — `0.9.1...release/0.10.0` lists 39 commits going back to
December 2024, when the true delta is 25.

`release.sh status` detects this (it compares the oldest commit in the range against
the previous release's date) and suggests the correct `--since` SHA: the newest
`Merge branch 'main' into develop` commit, which is where develop stood at the last
release.

Once 0.10.0 is merged with a real merge commit per Phase 2 Step B, the problem is
gone for good and plain tags work as boundaries again.

## Troubleshooting

- **Working tree not clean**: don't stash or discard anything automatically — show
  the user `git status` and ask. It may be work worth keeping.
- **bumpver refuses to bump ("invariant violated")**: usually a tag that exists on
  the remote but not locally, or vice versa. `git fetch --tags origin` and retry;
  bumpver cross-checks `pyproject.toml` against VCS tags.
- **`release.sh merge` refuses**: see Phase 2 Step B. Do not work around it by
  squashing.
- **A published release has wrong notes**: edit them freely. The publish workflow
  triggers only on `published`, not `edited`, so editing notes will not re-run the
  upload.
- **`workflow-status` reports no runs**: GitHub keeps run history for 400 days, and
  releases here are less frequent than that. Not an error.
- **User asks for another rc without a version**: reuse the version from the existing
  `release/X.Y.Z` branch rather than asking them to repeat it.
