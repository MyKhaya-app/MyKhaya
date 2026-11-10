import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

// Regression coverage for the "calendar appears zoomed/shifted after
// saving an event with a Location" bug. WebKit auto-zooms the page when a
// text input under 16px takes focus, and the zoom was still in effect after
// the event sheet closed. The cause was a class on Calendar's Location
// <input> (.icon-row-control, 0.95rem) outranking the mobile rule that sets
// every input to 16px.
//
// Since the event editor moved to the shared form primitives
// (components/form-layout.tsx), Location is a plain FormField input with no
// class of its own, so the plain mobile rule applies directly. This pins
// that: the 16px rule still exists, and nothing the editor's fields are
// styled by sets a smaller font-size. jsdom has no cascade, so the zoom
// itself cannot be reproduced here.

const css = readFileSync(join(process.cwd(), "app", "styles.css"), "utf8").replace(/\r\n/g, "\n");
const page = readFileSync(join(process.cwd(), "app", "calendar", "page.tsx"), "utf8");

function ruleBodies(selectorPattern: RegExp): string[] {
  return [...css.matchAll(new RegExp(`(^|\\n)\\s*${selectorPattern.source}\\s*\\{([^}]*)\\}`, "g"))].map(
    (match) => match[2]!,
  );
}

describe("styles.css — Location input keeps the 16px anti-zoom font-size on mobile", () => {
  it("sets every input to 16px inside an @media (max-width: 800px) block", () => {
    const ruleIndex = css.indexOf("\n  input,\n  select,\n  textarea {\n    font-size: 16px;");
    expect(ruleIndex).toBeGreaterThan(-1);
    const mediaIndex = css.lastIndexOf("@media (max-width: 800px)", ruleIndex);
    expect(mediaIndex).toBeGreaterThan(-1);
    const between = css.slice(mediaIndex, ruleIndex);
    expect((between.match(/\{/g) ?? []).length).toBeGreaterThan((between.match(/\}/g) ?? []).length);
  });

  it("renders Location as a plain FormField input, with no class to outrank that rule", () => {
    const location = page.match(/<FormField label="Location">[\s\S]*?<\/FormField>/)?.[0];
    expect(location).toBeDefined();
    expect(location).toContain('name="location"');
    expect(location).not.toContain("className");
  });

  it("does not shrink the font of shared form fields or the Calendar event editor", () => {
    const bodies = [
      ...ruleBodies(/\.form-field > :is\(input, select, textarea\)/),
      ...ruleBodies(/\.calendar-event-form[^{]*/),
    ];
    expect(bodies.length).toBeGreaterThan(0);
    for (const body of bodies) expect(body).not.toMatch(/font-size/);
  });

  it("no longer carries the .icon-row-control class that caused the bug", () => {
    expect(css).not.toContain(".icon-row-control");
    expect(page).not.toContain("icon-row-control");
  });
});
