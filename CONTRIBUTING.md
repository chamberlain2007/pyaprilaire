# Contributing

> AI agents working in this repo: see [AGENTS.md](AGENTS.md) for a quick summary of these conventions.

## Commit messages and PR titles

This project follows [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/). This applies to both individual commit messages and pull request titles, and applies equally to human contributors and AI agents.

Format:

```
<type>[optional scope]: <description>

[optional body]

[optional footer(s)]
```

Common types:

- `feat`: a new feature
- `fix`: a bug fix
- `docs`: documentation only changes
- `refactor`: a code change that neither fixes a bug nor adds a feature
- `test`: adding or correcting tests
- `chore`: tooling, CI, dependencies, or other maintenance
- `perf`: a performance improvement

A breaking change is indicated with a `!` after the type/scope (e.g. `feat!: change socket API`) and/or a `BREAKING CHANGE:` footer.

For a breaking change, **put the `!` in the pull request title**, not only on a commit inside the branch. Pull requests are squash-merged, so the PR title becomes the commit subject on `develop` and is what GitHub's release notes are built from. A `!` that appears only on an inner commit ends up buried in the squash body, where the changelog will not show it - which is what happened with [#79](https://github.com/chamberlain2007/pyaprilaire/pull/79), a real breaking change whose PR title carried no marker.

When a change breaks downstream code, also include a `BREAKING CHANGE:` footer describing what breaks and what to do about it. That text is quoted verbatim into the release notes as the migration note, so write it for someone upgrading.

Examples:

```
fix: reconnect socket after COS packet timeout
feat(mock_server): support custom response delay
docs: document automation mode prerequisite
```

Commit messages are checked locally via the `conventional-pre-commit` hook (see below), and PR titles are checked in CI.

Release PRs (`release/X.Y.Z` branches targeting `main`, titled `release: X.Y.Z`) are exempt from PR title linting, since `release` isn't a Conventional Commits type.

## Pull requests

Every pull request should use the [pull request template](.github/pull_request_template.md), which is applied automatically when opening a PR. This is not optional, and it applies equally to human contributors and AI agents - an agent that opens a PR must read the template file and build the description from it rather than writing a description of its own shape.

Concretely, that means:

- Keep every heading from the template, spelled and ordered exactly as the template has them. Do not add, drop, rename, or reorder sections.
- Fill in each section. A section that genuinely does not apply gets `None` (or a one-line reason), never an empty body and never a deleted heading.
- Replace the `<!-- ... -->` prompts with real content. They are instructions for the author, not text to keep - a merged PR body should contain no leftover template comments.
- Keep the checklist, and tick a box only when the thing is actually true. Leave the rest unticked rather than removing them.
- In "Type of change", delete the entries that do not apply, leaving the one (or few) that do.

### Formatting PR descriptions and comments

Anything rendered as Markdown on GitHub - PR descriptions, PR and issue comments, review comments - should be written in flowing paragraphs. GitHub reflows paragraph text to the reader's window width, so manual wrapping is not needed and actively hurts: it fights the reader's width, and it turns into ragged half-lines as soon as anyone edits the text.

So:

- Write a paragraph as one continuous line, however long it runs. Do not hard-wrap prose at 72, 80, or 100 columns.
- Separate paragraphs with a blank line. That blank line is what makes a new paragraph - a single newline inside a paragraph is not a paragraph break, and a trailing double space to force a `<br>` is not one either.
- Use real Markdown structure for structure: headings, `-` lists, numbered lists, tables, fenced code blocks. Do not fake a list or a table by breaking lines by hand.
- Line breaks are still correct inside fenced code blocks, and each list item is still its own line - the rule above is about prose, not about literal content.

Commit message bodies are plain text rather than rendered Markdown, so the usual git convention of wrapping the body around 72 columns still applies there.

## Code comments

Code should read without narration. A comment earns its place only when it is one of:

1. A Python docstring on a module, class, or function.
2. A short note explaining a line that genuinely cannot be understood from the code itself - a magic value taken from the protocol spec, a non-obvious guard, a workaround whose reason is invisible at the call site.

Everything else comes out. In particular, do not write:

- Restatements of what the line already says (`# Ensure already disconnected` above a disconnect call).
- Design rationale, alternatives considered, or arguments for why the code is shaped the way it is.
- Change history - "used to", "before #82", "regression fix", pointers to a PR description. Git and the pull request carry that.
- Section banners and running commentary that narrate a file into chapters.

Keep what survives brief, a line or two. An explanation that needs paragraphs belongs in a docstring, in this file or the README, or in the pull request description - not in a comment block.

Docstrings follow the same brevity rule: state what the thing is or does, its parameters, what it returns, and what it raises - not why the implementation was chosen. This applies to tests as much as to library code.

## Linting

This project uses [ruff](https://docs.astral.sh/ruff/) for linting and formatting, and [pre-commit](https://pre-commit.com/) to run checks automatically. After installing the `dev` extra (`pip install -e .[dev]`), enable the hooks with:

```
pre-commit install --hook-type pre-commit --hook-type commit-msg
```

This lints/formats staged Python files and validates commit messages against Conventional Commits on each commit. You can also run it manually against the whole repo with `pre-commit run --all-files`.
