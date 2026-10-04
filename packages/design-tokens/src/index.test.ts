import { describe, expect, it } from "vitest";
import {
  contrastText,
  DEFAULT_CALENDAR_COLOUR,
  PALETTE_HEX,
  PALETTE_KEYS,
  resolveColour,
} from "./index";

describe("PALETTE_KEYS / PALETTE_HEX", () => {
  it("has ~24-30 colours, per the expanded calendar/category palette", () => {
    expect(PALETTE_KEYS.length).toBeGreaterThanOrEqual(24);
    expect(PALETTE_KEYS.length).toBeLessThanOrEqual(30);
  });

  it("gives every key a valid 6-digit hex value", () => {
    for (const key of PALETTE_KEYS) {
      expect(PALETTE_HEX[key]).toMatch(/^#[0-9A-F]{6}$/);
    }
  });

  it("never repeats the exact same hex value across two different keys", () => {
    const values = PALETTE_KEYS.map((key) => PALETTE_HEX[key]);
    expect(new Set(values).size).toBe(values.length);
  });

  it("DEFAULT_CALENDAR_COLOUR is the teal preset's hex", () => {
    expect(DEFAULT_CALENDAR_COLOUR).toBe(PALETTE_HEX.teal);
  });
});

describe("resolveColour", () => {
  it("resolves a known palette token to its hex value", () => {
    expect(resolveColour("emerald")).toBe(PALETTE_HEX.emerald);
  });

  it("passes a valid raw hex value through unchanged", () => {
    expect(resolveColour("#E27658")).toBe("#E27658");
  });

  it("is case-insensitive for a raw hex value", () => {
    expect(resolveColour("#e27658")).toBe("#e27658");
  });

  it("falls back to a deterministic colour for null/undefined/unrecognised input", () => {
    const first = resolveColour(null, "seed-a");
    const second = resolveColour(null, "seed-a");
    expect(first).toBe(second);
    expect(Object.values(PALETTE_HEX)).toContain(first);
  });
});

describe("contrastText", () => {
  it("chooses dark text for a light background", () => {
    expect(contrastText("#F2EDE3")).toBe("#233028");
  });

  it("chooses white text for a dark background", () => {
    expect(contrastText("#233028")).toBe("#FFFEFB");
  });

  it("chooses readable text for every preset in the expanded palette", () => {
    for (const key of PALETTE_KEYS) {
      const text = contrastText(PALETTE_HEX[key]);
      expect(["#233028", "#FFFEFB"]).toContain(text);
    }
  });

  it("falls back safely for a malformed hex value", () => {
    expect(contrastText("not-a-colour")).toBe("#FFFEFB");
  });
});
