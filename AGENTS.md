# Repository conventions

See [CONTRIBUTING.md](CONTRIBUTING.md) for full details.

- Commit messages and pull request titles must follow [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/) (e.g. `fix: reconnect socket after COS packet timeout`, `feat(mock_server): support custom response delay`), except release PRs (`release/X.Y.Z` -> `main`, titled `release: X.Y.Z`), which are exempt from title linting.
- For a breaking change, put the `!` in the **pull request title** (e.g. `feat(client)!: ...`), not only on a commit inside the branch - PRs are squash-merged, so the PR title is what release notes are built from. Add a `BREAKING CHANGE:` footer describing the break; it is quoted verbatim into the release notes.
- When opening a pull request, fill in the [PR template](.github/pull_request_template.md) rather than leaving its sections blank or deleting them.
- Run `ruff check` and `ruff format --check` before committing.
