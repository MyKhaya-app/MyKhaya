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

  // The status column used to size itself to the full acceptance timestamp,
  // squeezing "Terms & Conditions" into a one-word-wide column on a 440pt
  // iPhone. The stacked layout is now the default for every legal row, so it
  // also holds on WebViews without container queries (iOS 15).
  describe("default (phone) row layout", () => {
    const base = css.slice(css.indexOf("/* Legal document rows"), css.indexOf("@container legal-rows"));

    it("puts the status on its own row beneath the document information", () => {
      expect(base).toMatch(/\.legal-document-row \{[^}]*grid-template-columns: auto minmax\(0, 1fr\) auto;/s);
      expect(base).toMatch(/\.legal-document-row-status \{[^}]*flex-wrap: wrap;[^}]*grid-column: 2;[^}]*grid-row: 2;/s);
      expect(base).toMatch(/\.more-row-status \{[^}]*grid-column: 2;[^}]*grid-row: 2;/s);
    });

    it("keeps the chevron beside the document information across both rows", () => {
      expect(base).toMatch(/\.legal-document-row > svg \{[^}]*grid-column: 3;[^}]*grid-row: 1 \/ span 2;/s);
      expect(base).toMatch(/\.more-row-with-status > \.more-row-chevron \{[^}]*grid-column: 3;[^}]*grid-row: 1 \/ span 2;/s);
    });

    it("wraps titles between words instead of letter by letter", () => {
      expect(base).toMatch(/\.legal-document-row-copy strong \{[^}]*overflow-wrap: break-word;/s);
      expect(base).not.toMatch(/\.legal-document-row-copy strong \{[^}]*overflow-wrap: anywhere;/s);
    });
  });

  it("moves the status beside the text only when the list itself is wide", () => {
    expect(css).toMatch(/\.legal-document-rows \{[^}]*container: legal-rows \/ inline-size;/s);
    const wide = css.slice(css.indexOf("@container legal-rows (min-width: 34rem) {"));
    expect(wide.startsWith("@container legal-rows (min-width: 34rem) {")).toBe(true);
    expect(wide).toMatch(/\.legal-document-row \{[^}]*grid-template-columns: auto minmax\(0, 1fr\) minmax\(0, max-content\) auto;/s);
    expect(wide).toMatch(/\.legal-document-row-status,\s*\.more-row-status \{[^}]*grid-row: 1;[^}]*max-width: 15rem;/s);
    // No viewport breakpoint decides this any more.
    expect(css).not.toMatch(/@media \(max-width: 420px\) \{\s*\.legal-document-row \{[^}]*grid-template-columns/s);
  });
});
