# Contributing

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

Examples:

```
fix: reconnect socket after COS packet timeout
feat(mock_server): support custom response delay
docs: document automation mode prerequisite
```

Commit messages are checked locally via the `conventional-pre-commit` hook (see below), and PR titles are checked in CI.

## Pull requests

Every pull request should use the [pull request template](.github/pull_request_template.md), which is applied automatically when opening a PR. Fill in each section rather than deleting it.

## Linting

This project uses [ruff](https://docs.astral.sh/ruff/) for linting and formatting, and [pre-commit](https://pre-commit.com/) to run checks automatically. After installing the `dev` extra (`pip install -e .[dev]`), enable the hooks with:

```
pre-commit install --hook-type pre-commit --hook-type commit-msg
```

This lints/formats staged Python files and validates commit messages against Conventional Commits on each commit. You can also run it manually against the whole repo with `pre-commit run --all-files`.
