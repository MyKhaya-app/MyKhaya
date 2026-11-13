/**
 * Cross-route CSS collision guard.
 *
 * Next.js keeps a route's global stylesheet loaded after an in-app navigation
 * away from that route (it adds stylesheets as routes are visited and does not
 * remove them). So a stylesheet imported by one page also applies to every
 * other page the person reaches in the same tab without a full reload. If
 * another page renders markup that one of its rules matches, that page is
 * restyled by accident. This is what turned the marketing header's Sign in
 * link (class "signin") into a full-height block after visiting /login, and
 * left /founding-beta and the other marketing pages blank after Back.
 *
 * For every page, the guard works out which local stylesheets the page loads
 * itself (through its layouts and its transitive imports). For every
 * stylesheet it does not load, each rule is checked: if all the classes the
 * rule needs appear in that page's markup, the stylesheet would style the
 * page once it had leaked in, and the test fails.
 *
 * Deliberately shared styles are not collisions:
 * - stylesheets imported by a layout are global to that layout's routes by
 *   design (app/styles.css everywhere, the PCC stylesheet on its own host);
 * - @font-face and @keyframes blocks, and :root / :where(...) token blocks,
 *   only declare fonts, animations and custom properties.
 *
 * Fix a failure by scoping the rule under its page's own root class (for
 * example ".signin-page > .signin") or by giving the other page's element a
 * class of its own.
 */
import { existsSync, readdirSync, readFileSync } from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import { describe, expect, it } from "vitest";

const ROOT = __dirname;
const rel = (file: string) => relative(ROOT, file).replace(/\\/g, "/");
const read = (file: string) => readFileSync(file, "utf8").replace(/\r\n/g, "\n");

// --- Module graph -----------------------------------------------------------

const SOURCE_EXTENSIONS = [".tsx", ".ts", "/index.tsx", "/index.ts"];

function resolveImport(from: string, specifier: string): string | null {
  let base: string;
  if (specifier.startsWith("@/")) base = join(ROOT, specifier.slice(2));
  else if (specifier.startsWith(".")) base = resolve(dirname(from), specifier);
  else return null; // packages: not part of the app's own markup or CSS
  if (specifier.endsWith(".css")) return existsSync(base) ? base : null;
  for (const extension of ["", ...SOURCE_EXTENSIONS]) {
    const candidate = base + extension;
    if (existsSync(candidate) && /\.(tsx?|css)$/.test(candidate)) return candidate;
  }
  return null;
}

const importsCache = new Map<string, string[]>();
function importsOf(file: string): string[] {
  const cached = importsCache.get(file);
  if (cached) return cached;
  const source = read(file);
  const found: string[] = [];
  const pattern = /(?:import|export)\s+(?:[^"'`;]*?\s+from\s+)?["']([^"']+)["']|import\(\s*["']([^"']+)["']\s*\)/g;
  for (const match of source.matchAll(pattern)) {
    const target = resolveImport(file, match[1] ?? match[2] ?? "");
    if (target) found.push(target);
  }
  importsCache.set(file, found);
  return found;
}

function closure(entries: string[]): Set<string> {
  const seen = new Set<string>();
  const stack = [...entries];
  while (stack.length) {
    const file = stack.pop()!;
    if (seen.has(file)) continue;
    seen.add(file);
    if (!file.endsWith(".css")) stack.push(...importsOf(file));
  }
  return seen;
}

/** The layouts that wrap a page: app/layout.tsx down to the page's folder. */
function layoutsFor(page: string): string[] {
  const layouts: string[] = [];
  let folder = dirname(page);
  while (folder.startsWith(join(ROOT, "app"))) {
    const layout = join(folder, "layout.tsx");
    if (existsSync(layout)) layouts.push(layout);
    folder = dirname(folder);
  }
  return layouts;
}

// --- Markup ----------------------------------------------------------------

const classesCache = new Map<string, Set<string>>();
/** Class names a source file can put in markup: string literals inside
 *  className={...}, className="..." and template literals. */
function classesIn(file: string): Set<string> {
  const cached = classesCache.get(file);
  if (cached) return cached;
  const source = read(file);
  const classes = new Set<string>();
  const add = (text: string) => {
    for (const token of text.replace(/\$\{[^}]*\}/g, " ").split(/\s+/)) {
      if (/^-?[A-Za-z_][\w-]*$/.test(token)) classes.add(token);
    }
  };
  for (const match of source.matchAll(/className=(?:"([^"]*)"|'([^']*)')/g)) add(match[1] ?? match[2] ?? "");
  for (const match of source.matchAll(/className=\{/g)) {
    // Take the balanced {...} expression and every string literal inside it.
    let depth = 0;
    let end = match.index + "className=".length;
    for (; end < source.length; end += 1) {
      if (source[end] === "{") depth += 1;
      else if (source[end] === "}" && --depth === 0) break;
    }
    const expression = source.slice(match.index, end);
    for (const literal of expression.matchAll(/"([^"]*)"|'([^']*)'|`([^`]*)`/g)) {
      add(literal[1] ?? literal[2] ?? literal[3] ?? "");
    }
  }
  classesCache.set(file, classes);
  return classes;
}

// --- Stylesheets ----------------------------------------------------------

type Rule = { selector: string; classes: string[] };

/** Splits a selector list on top-level commas only (not inside :is(...)). */
function splitSelectorList(list: string): string[] {
  const parts: string[] = [];
  let depth = 0;
  let current = "";
  for (const character of list) {
    if (character === "(") depth += 1;
    if (character === ")") depth -= 1;
    if (character === "," && depth === 0) {
      parts.push(current);
      current = "";
    } else current += character;
  }
  parts.push(current);
  return parts.map((part) => part.trim()).filter(Boolean);
}

/** Every style rule's selectors, walking into @media/@supports/@container
 *  and skipping @font-face, @keyframes and other non-selector blocks. */
function rulesIn(css: string): Rule[] {
  const text = css.replace(/\/\*[\s\S]*?\*\//g, "");
  const rules: Rule[] = [];
  let index = 0;
  const walk = (insideKeyframes: boolean): void => {
    while (index < text.length) {
      const open = text.indexOf("{", index);
      const close = text.indexOf("}", index);
      if (open === -1 || (close !== -1 && close < open)) {
        index = close === -1 ? text.length : close + 1;
        return;
      }
      const prelude = text.slice(index, open).split(";").pop()!.trim();
      index = open + 1;
      if (prelude.startsWith("@")) {
        // @media and friends hold ordinary rules; @font-face, @keyframes and
        // the like hold no selectors that could match markup.
        walk(!/^@(media|supports|container|layer|scope)\b/.test(prelude));
        continue;
      }
      if (!insideKeyframes) {
        for (const selector of splitSelectorList(prelude)) {
          rules.push({ selector, classes: [...selector.matchAll(/\.(-?[A-Za-z_][\w-]*)/g)].map((m) => m[1]!) });
        }
      }
      // Skip the declaration block (no nesting in plain CSS).
      let depth = 1;
      while (index < text.length && depth > 0) {
        if (text[index] === "{") depth += 1;
        else if (text[index] === "}") depth -= 1;
        index += 1;
      }
    }
  };
  walk(false);
  return rules;
}

/** Token and font blocks that are shared on purpose. */
function isSharedDeclaration(selector: string): boolean {
  return /^(:root|:where\()/.test(selector) || selector === "html" || selector === "body";
}

// --- The graph for this app ---------------------------------------------

function filesNamed(folder: string, name: string): string[] {
  return readdirSync(folder, { withFileTypes: true }).flatMap((entry) => {
    const path = join(folder, entry.name);
    if (entry.isDirectory()) return filesNamed(path, name);
    return entry.name === name ? [path] : [];
  });
}

const pages = filesNamed(join(ROOT, "app"), "page.tsx");
const layouts = filesNamed(join(ROOT, "app"), "layout.tsx");
const layoutStylesheets = new Set(layouts.flatMap((layout) => importsOf(layout).filter((f) => f.endsWith(".css"))));

const pageGraph = pages.map((page) => {
  const files = closure([page, ...layoutsFor(page)]);
  const classes = new Set<string>();
  for (const file of files) if (!file.endsWith(".css")) for (const c of classesIn(file)) classes.add(c);
  const stylesheets = new Set([...files].filter((file) => file.endsWith(".css")));
  return { page, classes, stylesheets };
});

const routeStylesheets = [...new Set(pageGraph.flatMap((entry) => [...entry.stylesheets]))].filter(
  (sheet) => !layoutStylesheets.has(sheet),
);

type Collision = { stylesheet: string; selector: string; page: string };

function findCollisions(): Collision[] {
  const collisions: Collision[] = [];
  for (const sheet of routeStylesheets) {
    const rules = rulesIn(read(sheet)).filter((rule) => !isSharedDeclaration(rule.selector));
    for (const { page, classes, stylesheets } of pageGraph) {
      if (stylesheets.has(sheet)) continue; // the page loads this stylesheet itself
      for (const rule of rules) {
        if (rule.classes.length === 0 || rule.classes.every((c) => classes.has(c))) {
          collisions.push({ stylesheet: rel(sheet), selector: rule.selector, page: rel(page) });
        }
      }
    }
  }
  return collisions;
}

describe("route stylesheets never restyle other routes", () => {
  it("finds the app's pages and route stylesheets (sanity)", () => {
    expect(pages.length).toBeGreaterThan(20);
    const sheets = routeStylesheets.map(rel);
    expect(sheets).toEqual(expect.arrayContaining(["app/login/signin.css", "app/marketing-site.css", "app/signup-screen.css"]));
    expect(sheets).not.toContain("app/styles.css");
  });

  it("has no rule that would match another page's markup after an in-app navigation", () => {
    const report = findCollisions().map((c) => `${c.stylesheet}: "${c.selector}" would also style ${c.page}`);
    expect(report).toEqual([]);
  });

  it("detects the collision that broke Back navigation (regression)", () => {
    // The original defect: a bare ".signin" rule against the marketing
    // header's Sign in link, which every marketing page renders.
    const marketing = pageGraph.find((entry) => rel(entry.page) === "app/founding-beta/page.tsx")!;
    expect(marketing.stylesheets.has(join(ROOT, "app/login/signin.css"))).toBe(false);
    // The header's link as it was: class "signin" on a page without signin.css.
    const before = new Set([...marketing.classes, "signin"]);
    const matches = (rules: Rule[], classes: Set<string>) =>
      rules.some((rule) => rule.classes.every((c) => classes.has(c)));
    expect(matches(rulesIn(".signin { display: flex; min-height: 100dvh; }"), before)).toBe(true);
    expect(matches(rulesIn(".signin-page > .signin { display: flex; }"), before)).toBe(false);
    // The header link now has a class of its own.
    expect(marketing.classes.has("signin")).toBe(false);
    expect(marketing.classes.has("nav-signin")).toBe(true);
    // And the guard's parser sees through comments, @media and :is() lists.
    expect(rulesIn("/* .x {} */ @media (min-width: 1px) { .a :is(b, c) { color: red } }")).toEqual([
      { selector: ".a :is(b, c)", classes: ["a"] },
    ]);
    expect(rulesIn("@font-face { font-family: X; } @keyframes k { from { opacity: 0 } }")).toEqual([]);
  });
});
