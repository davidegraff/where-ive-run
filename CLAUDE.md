# Working on this repo

## All changes go through pull requests off `main`

- Start every piece of work on a new branch from the latest `origin/main`, ideally in its own git worktree, so that work in progress elsewhere in the repo doesn't get mixed in.
- Never commit or push directly to `main`. Open a pull request into `main` instead, one per change.
- Keep each pull request to one change, and include tests for what it changes.

**Why:** merging into `main` deploys straight to https://where-ive-run.fly.dev/ (see `.github/workflows/deploy.yml`). Pull requests run the same checks first, and they keep each change separate and easy to review.
