import { describe, expect, it, vi } from "vitest";
import { ApiError } from "@mykhaya/api-client";
import {
  classifyNativeProviderFailure,
  logNativeProviderFailure,
  newNativeAuthCorrelationId,
} from "./native-provider-errors";

// Shape of a Capacitor plugin rejection as delivered to JS.
function pluginRejection(code: string, data?: Record<string, unknown>) {
  return Object.assign(new Error("Apple sign-in could not be completed"), { code, data });
}

describe("classifyNativeProviderFailure", () => {
  it("treats Apple sheet cancellation as silent", () => {
    const failure = classifyNativeProviderFailure(pluginRejection("cancelled", { native_code: 1001 }), "apple", "provider");
    expect(failure).toMatchObject({ category: "cancelled", userMessage: null, nativeCode: 1001 });
  });

  it("treats the Android Google cancellation message as silent", () => {
    const failure = classifyNativeProviderFailure(new Error("Google sign-in was cancelled"), "google", "provider");
    expect(failure.category).toBe("cancelled");
    expect(failure.userMessage).toBeNull();
  });

  it("explains ASAuthorizationError.unknown (missing entitlement / no Apple Account) distinctly", () => {
    const failure = classifyNativeProviderFailure(pluginRejection("apple_unknown", { native_code: 1000 }), "apple", "provider");
    expect(failure.category).toBe("provider_unavailable_on_device");
    expect(failure.nativeCode).toBe(1000);
    expect(failure.userMessage).toMatch(/isn't available on this device/);
  });

  it("asks for an app update when the installed binary lacks the native plugin", () => {
    const failure = classifyNativeProviderFailure(
      Object.assign(new Error('"NativeExternalAuth" plugin is not implemented on ios'), { code: "UNIMPLEMENTED" }),
      "apple",
      "provider",
    );
    expect(failure.category).toBe("plugin_unavailable");
    expect(failure.userMessage).toMatch(/latest version of the MyKhaya app/);
  });

  it("maps other Apple failures to a retry message", () => {
    for (const code of ["apple_failed", "apple_invalid_response", "apple_not_handled", "invalid_credential", "apple_other"]) {
      const failure = classifyNativeProviderFailure(pluginRejection(code), "apple", "provider");
      expect(failure.category).toBe("provider_failed");
      expect(failure.userMessage).toBe("Apple sign-in could not be completed. Please try again or use your password.");
    }
  });

  it("keeps the server's user-safe message for API rejections", () => {
    const failure = classifyNativeProviderFailure(
      new ApiError(400, "The provider sign-in could not be verified."),
      "apple",
      "exchange",
    );
    expect(failure).toMatchObject({
      category: "server_rejected",
      status: 400,
      userMessage: "The provider sign-in could not be verified.",
    });
  });

  it("recognises a request that never reached the API", () => {
    const failure = classifyNativeProviderFailure(new TypeError("Load failed"), "apple", "start");
    expect(failure.category).toBe("network");
    expect(failure.userMessage).toMatch(/couldn't reach MyKhaya/);
  });

  it("recognises a locally expired attempt", () => {
    const failure = classifyNativeProviderFailure(
      new Error("The native sign-in attempt is no longer available."),
      "apple",
      "exchange",
    );
    expect(failure.category).toBe("attempt_expired");
  });

  it("uses link wording for the Security page", () => {
    const failure = classifyNativeProviderFailure(pluginRejection("apple_failed"), "apple", "provider", "link");
    expect(failure.userMessage).toBe("Could not connect Apple. Please try again.");
  });
});

describe("native provider diagnostics", () => {
  it("creates distinct opaque correlation ids", () => {
    const first = newNativeAuthCorrelationId();
    expect(first).toMatch(/^nauth-[0-9a-f]{16}$/);
    expect(newNativeAuthCorrelationId()).not.toBe(first);
  });

  it("logs categories and codes only", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const cause = Object.assign(new Error("secret-identity-token-value"), {
      code: "apple_failed",
      data: { native_code: 1004 },
    });
    logNativeProviderFailure("apple", "provider", "nauth-0123456789abcdef", classifyNativeProviderFailure(cause, "apple", "provider"));
    expect(warn).toHaveBeenCalledWith("[NATIVE AUTH] provider attempt failed", {
      provider: "apple",
      stage: "provider",
      category: "provider_failed",
      code: "apple_failed",
      native_code: 1004,
      status: null,
      correlation_id: "nauth-0123456789abcdef",
    });
    expect(JSON.stringify(warn.mock.calls)).not.toContain("secret-identity-token-value");
    warn.mockRestore();
  });
});
