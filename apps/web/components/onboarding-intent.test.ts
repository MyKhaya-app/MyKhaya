import { describe, expect, it } from "vitest";
import {
  clearOnboardingIntent,
  parseIntentFromParams,
  readOnboardingIntent,
  saveOnboardingIntent,
} from "./onboarding-intent";

describe("parseIntentFromParams", () => {
  it("reads a valid family/year selection", () => {
    expect(parseIntentFromParams("family", "year")).toEqual({ plan: "family", interval: "year" });
  });

  it("reads a valid family/month selection", () => {
    expect(parseIntentFromParams("family", "month")).toEqual({ plan: "family", interval: "month" });
  });

  it("defaults to free/month when both params are missing", () => {
    expect(parseIntentFromParams(null, null)).toEqual({ plan: "free", interval: "month" });
  });

  it("never trusts an out-of-enum plan value", () => {
    expect(parseIntentFromParams("family; DROP TABLE homes", "year").plan).toBe("free");
    expect(parseIntentFromParams("active", "year").plan).toBe("free");
  });

  it("never trusts an out-of-enum interval value", () => {
    expect(parseIntentFromParams("family", "lifetime").interval).toBe("month");
  });
});

class FakeStorage {
  private store = new Map<string, string>();
  getItem(key: string) {
    return this.store.get(key) ?? null;
  }
  setItem(key: string, value: string) {
    this.store.set(key, value);
  }
  removeItem(key: string) {
    this.store.delete(key);
  }
}

describe("saveOnboardingIntent / readOnboardingIntent / clearOnboardingIntent", () => {
  it("round-trips a saved intent", () => {
    const storage = new FakeStorage();
    saveOnboardingIntent({ plan: "family", interval: "year" }, storage);
    expect(readOnboardingIntent(storage)).toEqual({ plan: "family", interval: "year" });
  });

  it("returns null when nothing has been saved", () => {
    expect(readOnboardingIntent(new FakeStorage())).toBeNull();
  });

  it("treats a saved intent older than 48 hours as expired", () => {
    const storage = new FakeStorage();
    const savedAt = 1_000_000;
    storage.setItem(
      "mk_onboarding_intent",
      JSON.stringify({ plan: "family", interval: "year", savedAt }),
    );
    const justUnderLimit = savedAt + 48 * 60 * 60 * 1000 - 1;
    const justOverLimit = savedAt + 48 * 60 * 60 * 1000 + 1;
    expect(readOnboardingIntent(storage, justUnderLimit)).toEqual({ plan: "family", interval: "year" });
    expect(readOnboardingIntent(storage, justOverLimit)).toBeNull();
  });

  it("ignores a corrupted or tampered stored value rather than trusting it", () => {
    const storage = new FakeStorage();
    storage.setItem("mk_onboarding_intent", JSON.stringify({ plan: "enterprise", interval: "year", savedAt: Date.now() }));
    expect(readOnboardingIntent(storage)).toBeNull();
    storage.setItem("mk_onboarding_intent", "not json");
    expect(readOnboardingIntent(storage)).toBeNull();
  });

  it("clears a saved intent", () => {
    const storage = new FakeStorage();
    saveOnboardingIntent({ plan: "family", interval: "month" }, storage);
    clearOnboardingIntent(storage);
    expect(readOnboardingIntent(storage)).toBeNull();
  });

  it("is a safe no-op with no storage available", () => {
    expect(() => saveOnboardingIntent({ plan: "family", interval: "year" }, null)).not.toThrow();
    expect(readOnboardingIntent(null)).toBeNull();
    expect(() => clearOnboardingIntent(null)).not.toThrow();
  });
});
