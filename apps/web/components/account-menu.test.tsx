import { describe, expect, it } from "vitest";
import { maskEmail } from "./account-menu";

// Interaction/rendering coverage for AccountMenu itself lives in
// app-header.test.tsx (the desktop-dropdown describe block), which exercises
// it exactly as it is actually mounted — via AppHeader's avatar trigger.
// This file covers the one pure helper directly.
describe("maskEmail", () => {
  it("keeps the first character of the local part and masks the rest", () => {
    expect(maskEmail("anthony@example.com")).toBe("a•••@example.com");
  });

  it("never reveals the local part's real length", () => {
    expect(maskEmail("al@example.com")).toBe("a•••@example.com");
    expect(maskEmail("a@example.com")).toBe("a•••@example.com");
  });

  it("returns the input unchanged if there is no @ to anchor on", () => {
    expect(maskEmail("not-an-email")).toBe("not-an-email");
  });
});
