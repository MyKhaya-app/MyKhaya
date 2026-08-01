# Git Branching Strategy

MyKhaya has exactly two permanent branches:

- `main`: the latest deployable, stable application. Anthony alone merges to it.
- `dev`: all active development, fixes, documentation, refactoring and migrations.

Codex works on and may commit to `dev`. It never merges or pushes to `main`, creates release tags, creates GitHub Releases, deploys production, force-pushes, rewrites history or changes repository protection.

Long-lived feature, release and hotfix branches are not part of the normal workflow. A short-lived branch is created only when Anthony explicitly asks for one.

## Official workflow

1. Develop and test on `dev`.
2. Anthony reviews `dev`.
3. Anthony merges `dev` into `main` when it is ready.
4. Anthony creates the release tag.
5. Anthony deploys the tagged `main` revision.

There is no automatic promotion or merge strategy.
