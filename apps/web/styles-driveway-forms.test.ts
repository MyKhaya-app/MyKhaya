import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

// Driveway's forms are on the shared form primitives (docs/design/forms.md).
// The MOT nudge's own .drv-input set 15px text, which outranked the 16px
// mobile rule, so iOS zoomed the page when the Reminder or MOT expires field
// took focus. Its fields are now shared FormFields; this keeps the 15px rule
// from coming back. jsdom has no cascade, so the zoom itself cannot be
// reproduced here.

const css = readFileSync(join(process.cwd(), "app", "styles.css"), "utf8").replace(/\r\n/g, "\n");

describe("styles.css — Driveway form fields", () => {
  it("has no Driveway-specific input sizing left", () => {
    expect(css).not.toContain(".drv-input");
    expect(css).not.toMatch(/\.drv-page \.drv-field label/);
  });

  it("lets the overview's vehicle cards shrink to a phone's width", () => {
    // An implicit grid column could not be narrower than a card's
    // unwrapped content, so cards ran past 320px and 375px screens.
    const cards = css.match(/\n\.drv-page \.drv-cards \{[^}]*\}/)?.[0] ?? "";
    expect(cards).toContain("grid-template-columns: minmax(0, 1fr);");
    expect(css).toContain(".drv-page .drv-cards { grid-template-columns: repeat(2, minmax(0, 1fr)); }");
    expect(cards).not.toContain("overflow");
  });

  it("does not style the vehicle forms or the reminder sheet's fields itself", () => {
    expect(css).not.toMatch(/\.(vehicle-form|vehicle-reminder-form|driveway-form)\b[^{]*\{[^}]*font-size/);
  });
});
