import { describe, expect, it } from "vitest";
import { dispatchNativeBridgeEvent } from "./native-bridge";

describe("dispatchNativeBridgeEvent", () => {
  it("accepts every documented event variant without throwing", () => {
    expect(() => dispatchNativeBridgeEvent({ type: "navigation-changed", path: "/home" })).not.toThrow();
    expect(() => dispatchNativeBridgeEvent({ type: "unread-count-changed", count: 3 })).not.toThrow();
    expect(() => dispatchNativeBridgeEvent({ type: "auth-state-changed", signedIn: true })).not.toThrow();
    expect(() => dispatchNativeBridgeEvent({ type: "request-biometric-unlock" })).not.toThrow();
    expect(() =>
      dispatchNativeBridgeEvent({ type: "open-external-url", url: "https://example.com" }),
    ).not.toThrow();
    expect(() =>
      dispatchNativeBridgeEvent({ type: "share", title: "MyKhaya", url: "https://mykhaya.app" }),
    ).not.toThrow();
  });
});
