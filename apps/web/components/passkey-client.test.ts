import { describe, expect, it, vi } from "vitest";
import {
  authenticateWithPasskey,
  createPasskey,
  passkeyWasCancelled,
  passkeysSupported,
} from "./passkey-client";

const browserMocks = vi.hoisted(() => ({
  startAuthentication: vi.fn(async () => ({ id: "assertion" })),
  startRegistration: vi.fn(async () => ({ id: "registration" })),
}));

vi.mock("@simplewebauthn/browser", () => browserMocks);

describe("passkey browser helpers", () => {
  it("reports unsupported browsers without affecting password fallback", () => {
    expect(passkeysSupported()).toBe(false);
  });

  it("passes server options to the registration and authentication ceremonies", async () => {
    const creation = await createPasskey('{"challenge":"create"}');
    const assertion = await authenticateWithPasskey('{"challenge":"get"}');

    expect(creation).toEqual({ id: "registration" });
    expect(assertion).toEqual({ id: "assertion" });
    expect(browserMocks.startRegistration).toHaveBeenCalledWith({
      optionsJSON: { challenge: "create" },
    });
    expect(browserMocks.startAuthentication).toHaveBeenCalledWith({
      optionsJSON: { challenge: "get" },
    });
  });

  it("recognises platform cancellation separately from verification errors", () => {
    expect(passkeyWasCancelled(new DOMException("cancelled", "NotAllowedError"))).toBe(true);
    expect(passkeyWasCancelled(new Error("failed"))).toBe(false);
  });
});
