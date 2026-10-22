import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

// Normalised so the checks hold on Windows checkouts with CRLF line endings.
const css = readFileSync(join(__dirname, "app", "styles.css"), "utf8").replace(/\r\n/g, "\n");

describe("legal pages layout", () => {
  it("pads the legal overview and document cards from one shared rule", () => {
    expect(css).toMatch(/\.legal-privacy-card,\s*\.legal-document-card \{[^}]*padding: clamp\(1rem, 3vw, 1\.5rem\)/s);
  });

  it("keeps the shared .card free of padding (pages supply their own inset)", () => {
    expect(css).toMatch(/\n\.card \{(?![^}]*padding)[^}]*\}/s);
  });

  it("wraps long words and URLs in rendered legal content and meta", () => {
    expect(css).toMatch(/\.legal-prose \{[^}]*min-width: 0;[^}]*overflow-wrap: anywhere;/s);
    expect(css).toMatch(/\.legal-meta \{[^}]*overflow-wrap: anywhere;/s);
    expect(css).toMatch(/\.legal-prose table \{[^}]*display: block;[^}]*max-width: 100%;[^}]*overflow-x: auto;/s);
    expect(css).toMatch(/\.legal-prose pre \{\s*white-space: pre-wrap;/);
  });

  it("insets overview rows from their bordered container", () => {
    expect(css).toMatch(/\.legal-document-row \{[^}]*padding: 0\.9rem 1rem;/s);
  });

  it("keeps the chevron beside the title block on narrow phones", () => {
    const narrow = css.slice(css.indexOf("@media (max-width: 420px) {\n  .legal-document-row {"));
    expect(narrow).toMatch(/\.legal-document-row > svg \{[^}]*grid-column: 3;[^}]*grid-row: 1 \/ span 2;/s);
    expect(narrow).toMatch(/\.legal-document-row-status \{[^}]*grid-row: 2;/s);
  });
});
