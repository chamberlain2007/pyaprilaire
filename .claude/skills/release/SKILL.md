---
name: release
description: Cut and ship a pyaprilaire release — draft a release candidate (rc) off develop, iterate rc's as needed, and then finalize and publish the real version. Use this whenever the user asks to "start a release", "cut a new version", "prepare a draft release", "make an rc", "bump the version", "release X.Y.Z", or "run/finish/publish the release". Covers the full lifecycle: release branch, PR to main, bumpver version bumps, git tags, and GitHub draft/published releases.
---

# Release pyaprilaire

This repo ships releases through a `release/X.Y.Z` branch that goes through one or
more **release candidates (rc)** before becoming the real, published version. There
are two phases, each triggered by the user explicitly:

- **Prepare draft release** — start a new release or cut another rc for one already
  in progress. Safe to run repeatedly; nothing here is public-facing in a way that's
  hard to undo (a branch, a PR, and *draft* GitHub releases).
- **Run release** — finalize the version, merge to `main`, and publish the real
  release. This is the irreversible, public step: publishing a non-prerelease
  GitHub release fires `.github/workflows/python-publish.yml`, which uploads to the
  **real PyPI**. Always confirm with the user before merging to `main` and before
  publishing, even though they invoked this skill directly — read back what you're
  about to do (version, target branch, "this goes to real PyPI") and get a
  go-ahead first.

Both phases need the `gh` CLI (authenticated) and `bumpver` (`pip install -e .[dev]`
pulls it in). Work from a clean working tree — check `git status` before touching
branches, and don't start a phase with local uncommitted changes lying around.

## Why the version math is simple

`pyproject.toml` already has `[tool.bumpver]` configured with `tag = true` and
`commit = true` (and `push = false`, so pushing is always an explicit step you take
below). That means every `bumpver update` call commits the version bump *and*
creates the matching annotated git tag locally in one shot — you don't need to
compute version numbers or tag names by hand, or track what rc you're on yourself.
bumpver reads the current version from `pyproject.toml` and from existing VCS tags,
so it always knows what "next" means.

- `bumpver update --set-version X.Y.Zrc0` — jump straight to an explicit version;
  used to start a brand-new release at rc0.
- `bumpver update --tag rc --tag-num` — bump the rc number (rc0 → rc1 → rc2 …) on
  whatever version is already checked out. This is what makes "cut another rc" cheap
  for the user: no version math, just run it on the release branch.
- `bumpver update --tag final` — strip the rc suffix, leaving the plain `X.Y.Z`.
  Used only in "Run release".

Each of these leaves an unpushed commit + annotated tag on your current branch. You
always push both explicitly afterward (`git push` and `git push origin <tag>`),
which keeps the point where things become visible to others deliberate rather than
implicit in the bumpver call.

## Phase 1: Prepare draft release

### Step 0 — figure out which case you're in

Ask the user for the target version if they haven't given one (e.g. `1.2.0`) — a
plain `MAJOR.MINOR.PATCH`, no rc suffix; you add that. Then check whether the
release branch already exists:

```bash
git fetch origin develop main
git ls-remote --heads origin "release/X.Y.Z"
```

- **No such branch** → this is a **new release**, starting at rc0.
- **Branch already exists** → this is **another rc** for a release already in
  flight. You don't need the user to state the rc number; bumpver derives the next
  one from the tags already on the branch.

### Step A — create or update the release branch

New release:

```bash
git checkout -b release/X.Y.Z origin/develop
git push -u origin release/X.Y.Z
```

Existing release (new rc) — bring it up to date with develop before cutting the
next rc, since the point of another rc is usually to pick up fixes that landed on
develop since the last one:

```bash
git checkout release/X.Y.Z
git pull origin release/X.Y.Z
git merge origin/develop --no-edit
```

If the merge conflicts, stop and resolve it with the user rather than guessing at
intent — these are real conflicts between develop and an in-flight release. Push
once resolved (or immediately if it merged clean):

```bash
git push origin release/X.Y.Z
```

### Step B — build this release's changelog so far

Before touching the PR, build the **cumulative changelog**: what the final release
notes would look like if you shipped everything merged so far, i.e. scoped from the
last real, published release up to the release branch's current tip. Follow "Release
notes format" below with `previous_tag_name` set to the last final release tag
(`gh release list --exclude-drafts --exclude-pre-releases --limit 1`; omit it if
there is no previous release) and `target_commitish` set to `release/X.Y.Z`. Save it
somewhere you can reuse it in the next two steps (e.g. `/tmp/release-notes.md`) —
you need this exact content twice: once for the PR body, and again for rc0's release
body (they're the same scope at rc0, since nothing has diverged yet).

### Step C — open or update the PR to main

The PR body should always read like the changelog for the release as it stands
right now, not a static placeholder — that's what makes it useful as a running
preview of what will ship. Use the changelog from Step B as the body every time:

First rc — check a PR doesn't already exist (`gh pr list --head release/X.Y.Z
--base main`), then create one:

```bash
gh pr create --base main --head release/X.Y.Z \
  --title "release: X.Y.Z" \
  --body-file /tmp/release-notes.md
```

Fill in the repo's PR template (`.github/pull_request_template.md`) if `gh pr
create` doesn't apply it automatically — put the changelog in the template's summary
section rather than discarding the template.

Later rc's — the PR already exists, but its body is now stale (it only reflects
what had merged as of the previous rc). Refresh it with the changelog you just
rebuilt in Step B, so it reflects everything merged up to *this* rc:

```bash
gh pr edit release/X.Y.Z --body-file /tmp/release-notes.md
```

### Step D — bump the version on the release branch

New release (rc0):

```bash
bumpver update --set-version X.Y.Zrc0
```

Another rc on an existing release:

```bash
bumpver update --tag rc --tag-num
```

Then push the branch and the tag bumpver just created (the exact tag name, e.g.
`X.Y.Zrc1`, is printed in bumpver's output):

```bash
git push origin release/X.Y.Z
git push origin X.Y.Zrc<N>
```

### Step E — draft the GitHub release with the changelog

Unlike the PR body, each rc's *own* release notes should show only what's new
*since the last rc*, not the whole release again — the PR is the cumulative view,
the rc releases are the per-rc deltas:

- **rc0**: identical scope to the cumulative changelog you already built in Step B
  (there's no previous rc to delta against) — reuse that file as-is.
- **rc1 and later**: rebuild the changelog from "Release notes format" with
  `previous_tag_name` set to the *previous rc tag of this same release* instead
  (e.g. rc2's notes start at rc1), so only newly merged PRs show up. Don't reuse
  the Step B file here — it's cumulative-scoped, this one needs to be delta-scoped.

```bash
gh release create X.Y.Zrc<N> \
  --target release/X.Y.Z \
  --title "X.Y.Zrc<N>" \
  --draft --prerelease \
  --notes-file /tmp/release-notes.md
```

`--draft` means nothing publishes or fires the PyPI workflow yet — it's just
visible in the repo's Releases tab for review. Report the PR link and the draft
release link back to the user; that's the deliverable for this phase.

## Release notes format

Both rc and final releases use the same three-part shape — a narrative paragraph,
then the mechanical PR list, then the compare link — rather than a bare
auto-generated list:

1. **A short narrative paragraph.** One paragraph, prose, no bullets: describe what
   the release actually does for someone using the library (new device support, a
   protocol fix, an API change), grouped by theme rather than restating each PR
   title in order. Base it on the PR titles (and, for anything whose title alone
   doesn't explain the "why," a quick `gh pr view <number>` to check the body) —
   don't pad it with filler like "this release contains various improvements."
2. **A bulleted list of the PRs**, each formatted exactly like GitHub's own
   changelog entries: `<PR title> by @<author> in #<number>`.
3. **The full-changelog compare link**, e.g. `Full Changelog: 0.9.0...0.9.1`.

Get parts 2 and 3 for free from GitHub's notes generator instead of composing them
by hand — it already produces exactly this format — and only write part 1 yourself:

```bash
gh api repos/chamberlain2007/pyaprilaire/releases/generate-notes \
  -f tag_name=<tag-or-branch> \
  -f target_commitish=<branch> \
  -f previous_tag_name=<previous-tag> \
  --jq .body
```

`previous_tag_name` is what sets the scope — it's the "since when" for both the PR
list and the compare link — so pick it deliberately each time you build notes
rather than defaulting it:

- Building the **cumulative changelog** (Phase 1 Step B, and Phase 2 Step C): use
  the last real, published release tag.
- Building a **per-rc delta** (Phase 1 Step E for rc1+): use the previous rc tag of
  this same release.

(omit `-f previous_tag_name=...` entirely in either case if there's nothing to
diff against — the very first release, or the very first rc). `tag_name` mostly
just controls the label in the compare link; when you're building the PR's
changelog before the rc tag exists yet (Phase 1 Step B), pass the branch name
(`release/X.Y.Z`) instead of a not-yet-created tag — it's a valid ref, so the
compare link resolves, and you don't need to predict the next rc number to build
it.

This returns a `## What's Changed` section with one `* <title> by @<author> in
#<number>` line per merged PR, followed by a `**Full Changelog**: <compare-url>`
line that GitHub renders as `Full Changelog: <old-tag>...<new-tag>`. Read those PR
titles, write your narrative paragraph, then assemble the final file with all
three parts, keeping the generated section (list + compare link) intact rather
than reconstructing it:

```
<your narrative paragraph>

## What's Changed
<the bulleted PR list from generate-notes, unchanged>

**Full Changelog**: <the compare link from generate-notes, unchanged>
```

Save that to a file and pass it via `--notes-file` (or `--body-file` for the PR)
when you use it. You'll rebuild this multiple times across one rc cut with
different scopes — don't reuse a stale file across steps that need different
scopes (see Phase 1 Steps B and E). Don't hand-roll the bullet list or the compare
link yourself either — reusing GitHub's generated ones keeps author handles, PR
numbers, and link formatting exactly right.

## Phase 2: Run release

Only start this once the user confirms the release is actually ready to ship — this
phase merges to `main` and can publish to real PyPI.

### Step A — strip the rc suffix

```bash
git checkout release/X.Y.Z
git pull origin release/X.Y.Z
bumpver update --tag final
git push origin release/X.Y.Z
```

This leaves a final commit on the release branch at the plain `X.Y.Z` version, plus
a local annotated tag `X.Y.Z` (not yet pushed — push it in Step C, after the merge,
so the tag's commit is verified to be part of `main`'s history first).

### Step B — merge to main

Confirm with the user before this step: merging is what makes the release branch's
content land on `main`. Use a real merge (not squash/rebase) so the tagged bumpver
commit stays intact and part of `main`'s history:

```bash
gh pr merge --merge <PR-number-or-release/X.Y.Z>
```

If the PR can't merge cleanly (branch protection, required checks, conflicts),
surface that to the user rather than forcing it through.

### Step C — push the final tag and publish the release

```bash
git fetch origin main
git push origin X.Y.Z
```

Create the release as a draft first, then publish it as an explicit, confirmed
second action — publishing is the point of no return (fires the real-PyPI upload).
Build the notes the same way as in "Release notes format" above — narrative
paragraph plus the generated PR list — using `previous_tag_name` set to the
previous *final* release tag (omit it if this is the first release ever), not any
of this release's own rc tags, so the final notes summarize the whole release
rather than just the last rc's delta:

```bash
gh release create X.Y.Z \
  --target main \
  --title "X.Y.Z" \
  --draft \
  --notes-file /tmp/release-notes.md
```

Read the draft back to the user (or point them at its URL) and confirm they want it
live, then:

```bash
gh release edit X.Y.Z --draft=false
```

This is not a prerelease, so `python-publish.yml` uploads the build to the real
PyPI. Report the published release URL and confirm the PyPI upload workflow run
looks good (`gh run list --workflow python-publish.yml --limit 1`).

## Troubleshooting

- **Working tree not clean**: don't stash or discard anything automatically — show
  the user `git status` and ask how to proceed. It may be in-progress work worth
  keeping.
- **bumpver refuses to bump ("invariant violated")**: usually means the local repo
  is missing a tag that exists on the remote, or vice versa. Run `git fetch --tags
  origin` and retry; bumpver cross-checks `pyproject.toml` against VCS tags.
- **No prior release for `previous_tag_name`**: this is normal for the very first
  release ever cut, or the first rc of a release where nothing has been tagged yet
  — just omit that parameter when calling `generate-notes`.
- **User asks for another rc without giving a version**: that's expected and fine —
  reuse the version from the existing `release/X.Y.Z` branch name (or the current
  `pyproject.toml` version on that branch) rather than asking them to repeat it.
