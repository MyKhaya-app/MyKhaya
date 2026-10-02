import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

/**
 * Regression guard for the class of bug that caused the Notifications
 * module's own sub-nav/links to 404 on the real admin domain: a
 * "/control-centre"-prefixed navigation target (Link href, redirect()
 * target, router.push/replace target) works under `next dev` on a bare
 * localhost, but on admin[.dev].mykhaya.app, middleware.ts unconditionally
 * rewrites every request to "/control-centre${pathname}" — so a prefixed
 * target produces "/control-centre/control-centre/..." and a raw Next.js
 * 404. Every internal navigation target in this app must be a bare path.
 * See middleware.test.ts for the rewrite behaviour itself.
 */

const ROOTS = ["app", "components"];
const SOURCE_EXTENSIONS = [".tsx", ".ts"];
const EXCLUDED_FILE_SUFFIXES = [".test.tsx", ".test.ts"];
// Catches both a direct `href="/control-centre/..."` and a
// "/control-centre/..."-prefixed string literal sitting in a data-driven nav
// array (e.g. NotificationsSubNav's TABS, mapped into `<Link href={href}>`)
// — the actual shape the original bug took. Deliberately just "any string
// literal starting with /control-centre/", since no legitimate app/
// or components/ code needs that exact literal (the one legitimate
// same-family reference, PlatformShell's own path-stripping, uses a regex
// object `/^\/control-centre/`, not a quoted string).
const OFFENDING_PATTERNS = [/["']\/control-centre\//];

function collectSourceFiles(root: string): string[] {
  const files: string[] = [];
  for (const entry of readdirSync(root)) {
    const full = join(root, entry);
    const stats = statSync(full);
    if (stats.isDirectory()) {
      files.push(...collectSourceFiles(full));
      continue;
    }
    if (!SOURCE_EXTENSIONS.some((extension) => entry.endsWith(extension))) continue;
    if (EXCLUDED_FILE_SUFFIXES.some((suffix) => entry.endsWith(suffix))) continue;
    files.push(full);
  }
  return files;
}

describe("no /control-centre-prefixed navigation targets", () => {
  it("finds no hard-coded '/control-centre'-prefixed Link/redirect/router target under app/ or components/", () => {
    const offenders: string[] = [];
    for (const root of ROOTS) {
      for (const file of collectSourceFiles(root)) {
        const contents = readFileSync(file, "utf8");
        for (const pattern of OFFENDING_PATTERNS) {
          if (pattern.test(contents)) offenders.push(file);
        }
      }
    }
    expect(offenders).toEqual([]);
  });
});
