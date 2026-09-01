# Repository conventions

See [CONTRIBUTING.md](CONTRIBUTING.md) for full details.

- Commit messages and pull request titles must follow [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/) (e.g. `fix: reconnect socket after COS packet timeout`, `feat(mock_server): support custom response delay`), except release PRs (`release/X.Y.Z` -> `main`, titled `release: X.Y.Z`), which are exempt from title linting.
- For a breaking change, put the `!` in the **pull request title** (e.g. `feat(client)!: ...`), not only on a commit inside the branch - PRs are squash-merged, so the PR title is what release notes are built from. Add a `BREAKING CHANGE:` footer describing the break; it is quoted verbatim into the release notes.
- When opening a pull request, read [.github/pull_request_template.md](.github/pull_request_template.md) and build the description from it. Keep every heading, spelled and ordered as the template has them; fill in each section (`None` when it truly does not apply) rather than leaving it blank or deleting it; replace the `<!-- ... -->` prompts with real content instead of shipping them; and keep the checklist, ticking only the boxes that are actually true.
- Write PR descriptions and comments as flowing paragraphs: one continuous line per paragraph, a blank line between paragraphs. Do not hard-wrap prose at a column width, and do not use single newlines as paragraph breaks - GitHub reflows Markdown to the reader's width. Use real Markdown (headings, lists, tables, fenced code) for structure; literal line breaks belong only inside code blocks and between list items. Commit message bodies are plain text, so the usual ~72-column wrap still applies there.
- Run `ruff check` and `ruff format --check` before committing.
