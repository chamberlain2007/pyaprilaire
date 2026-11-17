"""Assemble release notes from a GitHub compare response.

Reads the JSON body of `GET /repos/{owner}/{repo}/compare/{base}...{head}` on stdin
and prints the notes body: narrative, breaking changes, the PR list, and the compare
link.

This builds the PR list itself rather than calling GitHub's generate-notes endpoint,
because that endpoint only accepts a *tag* as its boundary. Releases before 0.10.0
were squash-merged into main, so their tags do not contain the release branch's own
commits, and the only correct boundary for those ranges is a commit SHA. The output
format is the same as GitHub's.
"""

from __future__ import annotations

import argparse
import json
import re
import sys

# A squash merge lands as "<pr title> (#123)"; a merge commit as "Merge pull request
# #123 from owner/branch" with the real title on a later line.
SQUASH_PR = re.compile(r"\s*\(#(\d+)\)\s*$")
MERGE_PR = re.compile(r"^Merge pull request #(\d+) from ")

# Conventional Commits marks a breaking change two ways, and this repo has used both.
# The leading "* " allows for commit subjects concatenated into a squash body, which
# is where the marker usually ends up: the squash *subject* is the PR title, and a PR
# title carrying the "!" is a newer convention than some of the history.
BANG_MARKER = re.compile(r"^\*?[ \t]*[a-z]+(\([^)]*\))?!:", re.MULTILINE)
BREAKING_FOOTER = re.compile(r"^BREAKING[ -]CHANGE:", re.MULTILINE)


def commit_author(commit: dict) -> str:
    """The GitHub handle where we have one, else the raw commit author name."""
    author = commit.get("author") or {}
    if author.get("login"):
        return "@" + author["login"]
    return (commit.get("commit", {}).get("author") or {}).get("name", "unknown")


def parse_commit(commit: dict) -> dict:
    message = commit.get("commit", {}).get("message", "")
    lines = message.split("\n")
    subject = lines[0].strip()

    pr = None
    title = subject

    merge = MERGE_PR.match(subject)
    if merge:
        pr = int(merge.group(1))
        # The PR title is the first non-empty line of the body.
        title = next((ln.strip() for ln in lines[1:] if ln.strip()), subject)
    else:
        squash = SQUASH_PR.search(subject)
        if squash:
            pr = int(squash.group(1))
            title = SQUASH_PR.sub("", subject).strip()

    return {
        "sha": commit.get("sha", ""),
        "message": message,
        "subject": subject,
        "title": title,
        "pr": pr,
        "author": commit_author(commit),
    }


def breaking_note(message: str) -> str | None:
    """The BREAKING CHANGE footer text: its paragraph, verbatim.

    This is the migration note. It is quoted rather than summarised, because a
    paraphrase of "what will break" is worse than useless to someone upgrading.
    """
    lines = message.split("\n")
    for i, line in enumerate(lines):
        if BREAKING_FOOTER.match(line):
            paragraph = []
            for follow in lines[i:]:
                if not follow.strip():
                    break
                paragraph.append(follow.strip())
            text = " ".join(paragraph)
            return re.sub(r"^BREAKING[ -]CHANGE:\s*", "", text).strip()
    return None


def is_breaking(message: str) -> bool:
    return bool(BANG_MARKER.search(message) or BREAKING_FOOTER.search(message))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--owner", required=True)
    ap.add_argument("--repo", required=True)
    ap.add_argument("--base", required=True, help="boundary ref the notes start from")
    ap.add_argument(
        "--head", required=True, help="ref being released, for the compare link"
    )
    ap.add_argument("--narrative", help="file holding the narrative paragraph")
    args = ap.parse_args()

    payload = json.load(sys.stdin)
    commits = [parse_commit(c) for c in payload.get("commits", [])]

    total = payload.get("total_commits", len(commits))
    if total > len(commits):
        print(
            f"warning: compare returned {len(commits)} of {total} commits "
            "(the API caps a comparison at 250); notes may be incomplete",
            file=sys.stderr,
        )

    repo_url = f"https://github.com/{args.owner}/{args.repo}"
    out: list[str] = []

    if args.narrative:
        with open(args.narrative) as fh:
            narrative = fh.read().strip()
        if narrative:
            out.append(narrative)

    breaking = [c for c in commits if is_breaking(c["message"])]
    if breaking:
        out.append("## Breaking changes")
        entries = []
        for c in breaking:
            where = f"#{c['pr']}" if c["pr"] else c["sha"][:7]
            note = breaking_note(c["message"])
            entry = f"* **{c['title']}** in {where}"
            if note:
                entry += f"\n  {note}"
            entries.append(entry)
        out.append("\n".join(entries))

    # Commits with no PR - the bumpver bump, back-merges - are omitted, matching
    # what GitHub's own generated notes list.
    with_prs = [c for c in commits if c["pr"]]
    if with_prs:
        out.append("## What's Changed")
        out.append(
            "\n".join(
                f"* {c['title']} by {c['author']} in {repo_url}/pull/{c['pr']}"
                for c in with_prs
            )
        )

    out.append(f"**Full Changelog**: {repo_url}/compare/{args.base}...{args.head}")

    print("\n\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
