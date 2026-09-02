#!/usr/bin/env bash
#
# release.sh - GitHub operations for cutting and shipping a pyaprilaire release.
#
# Deliberately does not use the `gh` CLI: this runs in sandboxes where gh is not
# installed. Everything goes through the REST API with curl, authenticating from
# GH_TOKEN / GITHUB_TOKEN (or `gh auth token` if that binary happens to exist), so
# there is one code path for a maintainer's laptop and for an agent sandbox.
#
# Every mutating subcommand accepts --dry-run, which prints the request instead of
# sending it.

set -euo pipefail

API="https://api.github.com"
DRY_RUN=0

die() { printf 'error: %s\n' "$*" >&2; exit 1; }
warn() { printf 'warning: %s\n' "$*" >&2; }

usage() {
  cat <<'USAGE'
usage: release.sh <command> [options]

  status X.Y.Z
      Report the state of a release: whether release/X.Y.Z exists, the version on
      it, the last final release tag, the highest rc tag, the open PR, and the
      boundary ref to scope release notes against.

  notes --tag TAG --target REF --since REF [--narrative FILE]
      Print assembled release notes: narrative, breaking changes, the PR list, and
      the compare link. --since accepts a tag OR a commit SHA.

  pr-upsert X.Y.Z --body-file FILE
      Create the release PR (release/X.Y.Z -> main, titled "release: X.Y.Z") or
      update its body if it already exists.

  release-upsert TAG --target REF --notes-file FILE [--prerelease] [--draft]
      Create the GitHub release for TAG, or update it if it already exists.

  publish TAG
      Flip a draft release to published. This is the irreversible step: it fires
      python-publish.yml, which uploads to PyPI.

  merge X.Y.Z
      Merge the release PR with a real merge commit (never a squash).

  workflow-status
      Report the most recent python-publish.yml run.

Common options: --dry-run, --help
USAGE
}

# ---------------------------------------------------------------- setup

require_deps() {
  local missing=()
  for bin in curl jq python3 git; do
    command -v "$bin" >/dev/null 2>&1 || missing+=("$bin")
  done
  (( ${#missing[@]} == 0 )) || die "missing required commands: ${missing[*]}"
}

resolve_token() {
  if [[ -n ${GH_TOKEN:-} ]]; then TOKEN=$GH_TOKEN
  elif [[ -n ${GITHUB_TOKEN:-} ]]; then TOKEN=$GITHUB_TOKEN
  elif command -v gh >/dev/null 2>&1 && TOKEN=$(gh auth token 2>/dev/null) && [[ -n $TOKEN ]]; then :
  else
    die "no GitHub token: set GH_TOKEN or GITHUB_TOKEN (or authenticate the gh CLI)"
  fi
}

resolve_repo() {
  local remote slug
  remote=$(git remote get-url origin 2>/dev/null) || die "not in a git repo with an 'origin' remote"
  slug=${remote#*github.com}
  slug=${slug#[:/]}
  slug=${slug%.git}
  slug=${slug%/}
  OWNER=${slug%%/*}
  REPO=${slug#*/}
  [[ -n $OWNER && -n $REPO && $OWNER != "$slug" ]] || die "could not parse owner/repo from origin remote: $remote"
}

# api METHOD PATH [JSON_BODY] - prints the response body, fails on non-2xx.
api() {
  local method=$1 path=$2 body=${3-}
  local out code
  out=$(mktemp)
  local -a args=(
    -sS -o "$out" -w '%{http_code}' -X "$method"
    -H "Authorization: Bearer $TOKEN"
    -H "Accept: application/vnd.github+json"
    -H "X-GitHub-Api-Version: 2022-11-28"
  )
  [[ -n $body ]] && args+=(-H "Content-Type: application/json" -d "$body")
  code=$(curl "${args[@]}" "$API$path") || { rm -f "$out"; die "curl failed for $method $path"; }
  if (( code < 200 || code >= 300 )); then
    printf 'GitHub API %s %s -> HTTP %s\n' "$method" "$path" "$code" >&2
    jq -r '.message // .' <"$out" >&2 2>/dev/null || cat "$out" >&2
    rm -f "$out"
    return 1
  fi
  cat "$out"
  rm -f "$out"
}

# Like api, but honours --dry-run. Use for anything that changes state.
api_write() {
  local method=$1 path=$2 body=${3-}
  if (( DRY_RUN )); then
    printf '[dry-run] %s %s%s\n' "$method" "$API" "$path"
    [[ -n $body ]] && printf '%s\n' "$body" | jq .
    return 0
  fi
  api "$method" "$path" "$body"
}

# Apply a jq filter to a real response, but pass --dry-run's printed request through
# untouched - there is no JSON to filter in that case.
emit() {
  if (( DRY_RUN )); then cat; else jq -r "$1"; fi
}

# ---------------------------------------------------------------- lookups

# All releases, newest first. Includes drafts, which is why we never use
# /releases/tags/{tag}: that endpoint cannot see a draft release.
all_releases() {
  api GET "/repos/$OWNER/$REPO/releases?per_page=100"
}

# The last released version proper: not a draft, not flagged prerelease, and with a
# plain MAJOR.MINOR[.PATCH] tag. The tag-shape check matters because every beta
# before 0.10.0 was published with prerelease=false, so the flag alone would happily
# return something like 0.7.1b0.
last_final_release_tag() {
  all_releases | jq -r '
    [ .[]
      | select(.draft == false and .prerelease == false)
      | select(.tag_name | test("^v?[0-9]+\\.[0-9]+(\\.[0-9]+)?$"))
    ] | first | .tag_name // empty'
}

# Highest rc tag for a given version, e.g. 0.10.0rc2. Read from the remote rather
# than the local clone so a stale local tag list cannot produce a wrong answer.
latest_rc_tag() {
  local version=$1
  git ls-remote --tags origin "refs/tags/${version}rc*" 2>/dev/null \
    | awk '{print $2}' \
    | sed 's#^refs/tags/##; s#\^{}$##' \
    | sort -u \
    | sort -t 'c' -k2 -n \
    | tail -1
}

open_pr_for_branch() {
  local branch=$1 out
  out=$(api GET "/repos/$OWNER/$REPO/pulls?state=open&base=main&head=$OWNER:$branch") || return 0
  jq -r 'first | .number // empty' <<<"$out"
}

release_json_for_tag() {
  local tag=$1
  all_releases | jq --arg t "$tag" 'map(select(.tag_name == $t)) | first // empty'
}

# Empty (not an error) when the branch does not exist - that is a normal answer for
# a release that has not been cut yet.
branch_sha() {
  local branch=$1 out
  out=$(api GET "/repos/$OWNER/$REPO/branches/$branch" 2>/dev/null) || return 0
  jq -r '.commit.sha // empty' <<<"$out"
}

file_at_ref() {
  local path=$1 ref=$2
  api GET "/repos/$OWNER/$REPO/contents/$path?ref=$ref" 2>/dev/null \
    | jq -r '.content // empty' | base64 -d 2>/dev/null || true
}

compare_json() {
  local base=$1 head=$2
  api GET "/repos/$OWNER/$REPO/compare/$base...$head"
}

# ---------------------------------------------------------------- status

cmd_status() {
  local version=${1-}
  [[ -n $version ]] || die "usage: release.sh status X.Y.Z"
  local branch="release/$version"

  local sha branch_version last_final latest_rc pr
  sha=$(branch_sha "$branch")
  last_final=$(last_final_release_tag)
  latest_rc=$(latest_rc_tag "$version")

  printf 'release_branch:      %s\n' "$branch"
  if [[ -n $sha ]]; then
    branch_version=$(file_at_ref pyproject.toml "$branch" | sed -n 's/^version = "\(.*\)"$/\1/p' | head -1)
    printf 'branch_exists:       yes (%s)\n' "${sha:0:7}"
    printf 'branch_version:      %s\n' "${branch_version:-unknown}"
    pr=$(open_pr_for_branch "$branch")
    if [[ -n $pr ]]; then
      printf 'open_pr:             #%s\n' "$pr"
    else
      printf 'open_pr:             none\n'
    fi
  else
    printf 'branch_exists:       no\n'
    printf 'open_pr:             none\n'
  fi
  printf 'last_final_release:  %s\n' "${last_final:-none}"
  printf 'latest_rc_tag:       %s\n' "${latest_rc:-none}"

  if [[ -z $sha ]]; then
    printf 'next_action:         new release - cut %s from develop, bump to %src0\n' "$branch" "$version"
  else
    printf 'next_action:         another rc - bump the rc number on %s\n' "$branch"
  fi

  # Which boundary release notes should be scoped against.
  local rc_boundary="${latest_rc:-${last_final:-}}"
  printf 'notes_since (rc):    %s\n' "${rc_boundary:-none - omit --since}"
  printf 'notes_since (final): %s\n' "${last_final:-none - omit --since}"
  printf 'notes_since (PR):    %s\n' "${last_final:-none - omit --since}"

  # Sanity check on the boundary: if the oldest commit in the range predates the
  # last release, the range is picking up already-shipped work. That happens when a
  # past release PR was squash-merged into main, which leaves develop's original
  # commits outside the tag's ancestry. Releases from 0.10.0 on use a real merge
  # commit, so this warning should stop appearing.
  if [[ -n $sha && -n $last_final ]]; then
    local released_at oldest count
    released_at=$(all_releases | jq -r --arg t "$last_final" 'map(select(.tag_name == $t)) | first | .published_at // empty')
    local cmp; cmp=$(compare_json "$last_final" "$branch" 2>/dev/null || true)
    if [[ -n $cmp ]]; then
      count=$(jq -r '.commits | length' <<<"$cmp")
      oldest=$(jq -r '.commits | first | .commit.committer.date // empty' <<<"$cmp")
      printf 'commits_in_range:    %s (since %s)\n' "$count" "$last_final"
      if [[ -n $oldest && -n $released_at && $oldest < $released_at ]]; then
        printf '\n'
        warn "the oldest commit in ${last_final}..${branch} is dated ${oldest%%T*}, which predates the"
        warn "${last_final} release (${released_at%%T*}). The range includes already-shipped work, because"
        warn "that release PR was squash-merged into main. Pass --since <sha> with the newest"
        warn "\"Merge branch 'main' into develop\" commit instead of the tag:"
        jq -r '.commits[] | select(.commit.message | startswith("Merge branch '\''main'\'' into develop")) | .sha' <<<"$cmp" \
          | tail -1 | sed 's/^/  suggested --since /' >&2
      fi
    fi
  fi
}

# ---------------------------------------------------------------- notes

cmd_notes() {
  local tag="" target="" since="" narrative=""
  while (( $# )); do
    case $1 in
      --tag) tag=$2; shift 2 ;;
      --target) target=$2; shift 2 ;;
      --since) since=$2; shift 2 ;;
      --narrative) narrative=$2; shift 2 ;;
      *) die "unknown option for notes: $1" ;;
    esac
  done
  [[ -n $tag ]] || die "notes: --tag is required"
  [[ -n $target ]] || die "notes: --target is required"
  [[ -z $narrative || -f $narrative ]] || die "notes: no such narrative file: $narrative"

  if [[ -z $since ]]; then
    warn "no --since given: listing every commit reachable from $target (correct only for a first release)"
    since=$(api GET "/repos/$OWNER/$REPO/commits?sha=$target&per_page=1" | jq -r 'last | .sha')
  fi

  compare_json "$since" "$target" \
    | python3 "$(dirname "${BASH_SOURCE[0]}")/build_notes.py" \
        --owner "$OWNER" --repo "$REPO" --base "$since" --head "$tag" \
        ${narrative:+--narrative "$narrative"}
}

# ---------------------------------------------------------------- mutations

cmd_pr_upsert() {
  local version=${1-}; shift || true
  [[ -n $version ]] || die "usage: release.sh pr-upsert X.Y.Z --body-file FILE"
  local body_file=""
  while (( $# )); do
    case $1 in
      --body-file) body_file=$2; shift 2 ;;
      *) die "unknown option for pr-upsert: $1" ;;
    esac
  done
  [[ -n $body_file && -f $body_file ]] || die "pr-upsert: --body-file must point at an existing file"

  local branch="release/$version" pr payload
  pr=$(open_pr_for_branch "$branch")

  if [[ -n $pr ]]; then
    payload=$(jq -n --rawfile body "$body_file" '{body: $body}')
    api_write PATCH "/repos/$OWNER/$REPO/pulls/$pr" "$payload" | emit '.html_url // empty'
    (( DRY_RUN )) || printf 'updated PR #%s\n' "$pr"
  else
    payload=$(jq -n \
      --arg title "release: $version" \
      --arg head "$branch" \
      --rawfile body "$body_file" \
      '{title: $title, head: $head, base: "main", body: $body}')
    api_write POST "/repos/$OWNER/$REPO/pulls" "$payload" | emit '.html_url // empty'
  fi
}

cmd_release_upsert() {
  local tag=${1-}; shift || true
  [[ -n $tag ]] || die "usage: release.sh release-upsert TAG --target REF --notes-file FILE [--prerelease] [--draft]"
  local target="" notes_file="" prerelease=false draft=false
  while (( $# )); do
    case $1 in
      --target) target=$2; shift 2 ;;
      --notes-file) notes_file=$2; shift 2 ;;
      --prerelease) prerelease=true; shift ;;
      --draft) draft=true; shift ;;
      *) die "unknown option for release-upsert: $1" ;;
    esac
  done
  [[ -n $target ]] || die "release-upsert: --target is required"
  [[ -n $notes_file && -f $notes_file ]] || die "release-upsert: --notes-file must point at an existing file"

  local existing id was_draft payload
  existing=$(release_json_for_tag "$tag")

  if [[ -n $existing ]]; then
    id=$(jq -r '.id' <<<"$existing")
    was_draft=$(jq -r '.draft' <<<"$existing")
    payload=$(jq -n --arg name "$tag" --rawfile body "$notes_file" --argjson pre "$prerelease" \
      '{name: $name, body: $body, prerelease: $pre}')
    if [[ $was_draft == true ]]; then
      payload=$(jq --argjson d "$draft" '. + {draft: $d}' <<<"$payload")
    elif [[ $draft == true ]]; then
      warn "release $tag is already published; refusing to turn it back into a draft"
    fi
    api_write PATCH "/repos/$OWNER/$REPO/releases/$id" "$payload" | emit '.html_url // empty'
  else
    payload=$(jq -n \
      --arg tag "$tag" --arg target "$target" --arg name "$tag" \
      --rawfile body "$notes_file" --argjson pre "$prerelease" --argjson draft "$draft" \
      '{tag_name: $tag, target_commitish: $target, name: $name, body: $body,
        prerelease: $pre, draft: $draft, make_latest: (if $pre then "false" else "true" end)}')
    api_write POST "/repos/$OWNER/$REPO/releases" "$payload" | emit '.html_url // empty'
  fi
}

cmd_publish() {
  local tag=${1-}
  [[ -n $tag ]] || die "usage: release.sh publish TAG"

  local existing id
  existing=$(release_json_for_tag "$tag")
  [[ -n $existing ]] || die "no release found for tag $tag - create it with release-upsert first"

  if [[ $(jq -r '.draft' <<<"$existing") != true ]]; then
    printf 'release %s is already published: %s\n' "$tag" "$(jq -r '.html_url' <<<"$existing")"
    return 0
  fi

  id=$(jq -r '.id' <<<"$existing")
  api_write PATCH "/repos/$OWNER/$REPO/releases/$id" '{"draft": false}' | emit '.html_url // empty'
}

cmd_merge() {
  local version=${1-}
  [[ -n $version ]] || die "usage: release.sh merge X.Y.Z"
  local branch="release/$version" pr payload
  pr=$(open_pr_for_branch "$branch")
  [[ -n $pr ]] || die "no open PR found for $branch"

  # Preflight: merge commits have to be enabled repo-wide, or this returns a bare
  # 405. Enabling them does not loosen develop, whose ruleset pins
  # allowed_merge_methods to ["squash"] independently.
  if [[ $(api GET "/repos/$OWNER/$REPO" | jq -r '.allow_merge_commit') != true ]]; then
    die "this repo has merge commits disabled, so the release PR can only be squashed.
  Squashing is exactly what must not happen here: it creates a new commit on main,
  stranding the bumpver tag outside main's history and leaving the release branch's
  commits outside the tag's ancestry, which makes every later changelog list
  already-shipped PRs.
  Fix: Settings > General > Pull Requests > enable 'Allow merge commits'."
  fi

  # merge_method=merge, never squash. Squashing the release PR creates a brand new
  # commit on main, which leaves the release branch's own commits outside the tag's
  # ancestry - that is what makes every later changelog list already-shipped PRs,
  # and it strands the bumpver tag outside main's history.
  payload=$(jq -n --arg title "release: $version" '{merge_method: "merge", commit_title: $title}')
  api_write PUT "/repos/$OWNER/$REPO/pulls/$pr/merge" "$payload" | emit '.message // empty'
}

cmd_workflow_status() {
  local runs
  runs=$(api GET "/repos/$OWNER/$REPO/actions/workflows/python-publish.yml/runs?per_page=1")
  if [[ $(jq -r '.total_count' <<<"$runs") == 0 ]]; then
    printf 'no python-publish.yml runs retained (GitHub keeps run history for 400 days)\n'
    return 0
  fi
  jq -r '.workflow_runs[0] | "status: \(.status)\nconclusion: \(.conclusion // "-")\nurl: \(.html_url)"' <<<"$runs"
}

# ---------------------------------------------------------------- dispatch

main() {
  local -a args=()
  for arg in "$@"; do
    case $arg in
      --dry-run) DRY_RUN=1 ;;
      --help|-h) usage; exit 0 ;;
      *) args+=("$arg") ;;
    esac
  done
  set -- "${args[@]+"${args[@]}"}"
  (( $# )) || { usage; exit 1; }

  require_deps
  resolve_token
  resolve_repo

  local cmd=$1; shift
  case $cmd in
    status)          cmd_status "$@" ;;
    notes)           cmd_notes "$@" ;;
    pr-upsert)       cmd_pr_upsert "$@" ;;
    release-upsert)  cmd_release_upsert "$@" ;;
    publish)         cmd_publish "$@" ;;
    merge)           cmd_merge "$@" ;;
    workflow-status) cmd_workflow_status "$@" ;;
    *) die "unknown command: $cmd (try --help)" ;;
  esac
}

main "$@"
