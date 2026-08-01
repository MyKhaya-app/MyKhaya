# Hotfix Process

Hotfix branches use `hotfix/*` and start from `main`.

## Flow

1. Create `hotfix/<name>` from `main`.
2. Implement and test the minimum safe fix.
3. Open pull request to `main`.
4. After merge, create/update stable tag if needed.
5. Merge the hotfix back into `dev` immediately.

This prevents the fix from being lost in the next development promotion.

## Rules

- Hotfixes are only for urgent production risk reduction.
- Keep scope narrow and auditable.
- Run quality and security checks before merge.
- Document any migration impact and rollback constraints.