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

Every pull request should use the [pull request template](.github/pull_request_template.md), which is applied automatically when opening a PR. Fill in each section rather than deleting it.

## Linting

This project uses [ruff](https://docs.astral.sh/ruff/) for linting and formatting, and [pre-commit](https://pre-commit.com/) to run checks automatically. After installing the `dev` extra (`pip install -e .[dev]`), enable the hooks with:

```
pre-commit install --hook-type pre-commit --hook-type commit-msg
```

This lints/formats staged Python files and validates commit messages against Conventional Commits on each commit. You can also run it manually against the whole repo with `pre-commit run --all-files`.
