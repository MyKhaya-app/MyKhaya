# Documentation Sync (BookStack)

PCC → Platform → **Documentation Sync** publishes this repository's `docs/`
Markdown to managed books inside a private BookStack shelf. Publishing is one-way (repository →
BookStack). Code: `apps/api/mykhaya/docs_sync.py`,
`apps/api/mykhaya/routers/platform_docs_sync.py`.

## How it works

- `docs/` is copied into the API image at build time (`apps/api/Dockerfile`).
  A DEV build carries the `dev` branch's docs and a PROD build carries
  `main`'s. No GitHub access or token is used. The branch label defaults from
  `MYKHAYA_ENVIRONMENT` (production → `main`, otherwise `dev`) and can be set
  with `MYKHAYA_DOCS_SYNC_BRANCH`. It is only used in page notices and links.
- A background loop in the **scheduler** checks every 30 seconds. It syncs
  when an administrator pressed **Sync now**, or when automatic sync is on and
  the bundled docs differ from the last successful sync (normally just after
  a deploy). Unchanged docs cause no BookStack calls. A PostgreSQL advisory
  lock prevents overlapping runs. After a failed automatic run it waits
  15 minutes before retrying.
- Each top-level folder under `docs/` becomes a publisher-owned BookStack book
  in the selected shelf. Root-level Markdown files go into the automatically
  managed `Repository Documentation` book. The first `# Heading` becomes the
  page name, and clashing names get their path appended. Nested folders become
  one-level chapters named from their relative folder path; BookStack chapters
  are not nested. Relative `.md` links are
  rewritten to GitHub links when a repository URL is set. Each page starts
  with a notice naming its source file and branch.
- Book, chapter and page IDs are stored per BookStack host and shelf, with an
  ownership marker and source path. Only objects created and tracked by this
  publisher are updated. Unchanged pages are skipped. A deleted managed page
  or chapter is recreated; nothing is ever deleted, and untracked/manual
  content is never edited. Changing the shelf or instance starts a fresh set
  of managed books and leaves earlier content untouched.
- Writes are paced at about 150 per minute, below BookStack's default API
  limit. A first sync of ~120 documents takes roughly a minute.

## Configure (per environment)

1. In BookStack, create a dedicated user (e.g. "MyKhaya Docs Sync") with a
  role that has the **"Access system API"** system permission, plus **view and
  update** on the selected shelf and **create/update** on books, chapters and
  pages. The account needs no delete permission and no access to unrelated
  shelves or books. Create an API token for that user. Shelf update is required
  because BookStack attaches a new book by updating the shelf's book ID list;
  the sync reads that list first and appends only its own book.
2. In PCC (Owner or Administrator), enter the BookStack URL (public HTTPS
   only), the token ID and secret, and optionally the GitHub repository URL
   (for source links) and a folder filter. Then **Save connection** and
   **Test connection**.
3. **Refresh shelves**, choose the shelf, then **Use this shelf**.
4. Press **Sync now** for the first publish, then optionally **Enable
   automatic sync**.

Every change needs recent sign-in and a reason, and is audited
(`docs_sync.*`). The token secret is stored encrypted and is never shown
again, logged or audited. Changing the URL requires re-entering the secret,
so a stored token is never sent to a new host, and it clears the book
selection and disables automatic sync.

## DEV and PROD

Settings, credentials, page associations and history live in each
environment's own database. Nothing is configured by default, and nothing is
copied between environments. PROD stays inactive until an administrator
configures it in PROD's PCC. Use a different BookStack shelf (or instance)
for each environment.

## Troubleshooting

| Status message | Meaning |
| --- | --- |
| "must resolve only to public internet addresses" | URL points at a private, loopback or metadata address; not allowed |
| "rejected the API token, or it lacks permission" | Wrong token, token expired, or missing "Access system API" / book permissions |
| "Could not connect" / "did not respond in time" | Network, DNS or BookStack down; the next run retries |
| "rate limit reached" | The run stopped part-way; progress is saved and the next run continues |
| "bundled documentation folder is missing" | The image was built without `docs/`; rebuild from the repository |

A sync failure is recorded on the page and never affects other MyKhaya
features.
