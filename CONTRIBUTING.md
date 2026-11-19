# Contributing

Bug reports and pull requests are welcome, especially new Shops.

## Setup and tests

See "Development" in the [README](README.md). Run `python -m pytest -q` before opening a pull request; the tests
need no network, and CI runs them on every pull request.

## Adding a Shop

A Shop whose pages carry schema.org JSON-LD needs no code: add it under Settings > Shops (`app/shops/custom.py`).
Shops that need their own parsing get one adapter in `app/shops/`, registered in `BUILTIN` in `app/shops/__init__.py`. Start from a small one such
as `coolblue.py`:

- Subclass `Shop` (`app/shops/base.py`) and set `key` to the Shop's domain (e.g. `coolblue.be`).
- Implement `search(query)`, returning up to a few `Hit`s. `self.term(query)` gives the EAN, model number or name.
- Product pages are read from their schema.org JSON-LD by default (`hit` and `parse`); override them only when the
  Shop doesn't publish usable JSON-LD.
- Set `needs_browser = True` only when plain HTTP is always blocked; otherwise the adapter retries once in Chromium
  by itself.
- Amounts are integer euro cents. A page that can't be read is a `FetchError`, never a guessed price.

Save a search page and a product page as gzipped fixtures in `tests/fixtures/` (`<shop>_search.html.gz`,
`<shop>_product.html.gz`) and add tests in `tests/test_shops.py` like the existing ones.

Be polite to Shops: don't lower the minimum check interval (1 hour).

## Issue triage

New issues get the `needs-triage` label from the issue templates. Nobody works on them until the maintainer
approves them.

- **Approve**: swap `needs-triage` for `ready-for-agent`. Only approve an issue that says what "done" looks like.
- **Reject**: close the issue.

`ready-for-agent` issues are worked manually: in a Claude Code session, ask it to "work the ready queue". The agent
then, for each issue from `gh issue list --label ready-for-agent`, one at a time:

- Creates a branch (`fix/<topic>` or `feat/<topic>`) from `main` and opens one pull request with `Fixes #<n>`; it
  never pushes to `main`.
- Runs `python -m pytest -q` before opening the pull request.
- When the issue is unclear, comments with its questions, swaps the label back to `needs-triage` and skips it.
- For a feature that touches several parts of the app (UI, database, scheduler), agrees the design with the
  maintainer in the session before writing code.
