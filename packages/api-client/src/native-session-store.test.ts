import { describe, expect, it } from "vitest";
import { InMemoryNativeSessionStore } from "./native-session-store";

describe("InMemoryNativeSessionStore", () => {
  it("returns null when nothing has been stored", async () => {
    const store = new InMemoryNativeSessionStore();
    expect(await store.get()).toBeNull();
  });

  it("stores and returns a session", async () => {
    const store = new InMemoryNativeSessionStore();
    await store.set({ token: "token-a" });
    expect(await store.get()).toEqual({ token: "token-a" });
  });

  it("clearIfMatches clears when the token matches the one currently stored", async () => {
    const store = new InMemoryNativeSessionStore();
    await store.set({ token: "token-a" });
    await store.clearIfMatches("token-a");
    expect(await store.get()).toBeNull();
  });

  it("clearIfMatches is a no-op when a newer token has already replaced the stale one — the exact race ADR 0010 requires this to prevent", async () => {
    const store = new InMemoryNativeSessionStore();
    await store.set({ token: "token-a" });
    // Simulates a rotation completing before a stale request's 401 arrives.
    await store.set({ token: "token-b" });
    await store.clearIfMatches("token-a");
    expect(await store.get()).toEqual({ token: "token-b" });
  });

  it("clear always removes the current session regardless of token", async () => {
    const store = new InMemoryNativeSessionStore();
    await store.set({ token: "token-a" });
    await store.clear();
    expect(await store.get()).toBeNull();
  });
});
