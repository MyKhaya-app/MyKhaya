// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@mykhaya/api-client";
import { recordLoginFailureDiagnostic } from "./auth-diagnostics";

// Regression coverage for the native iOS login investigation: the
// user-facing error message must stay generic, but recordLoginFailureDiagnostic
// is what actually lets a developer/operator tell "invalid credentials"
// apart from "server 5xx" apart from "CORS/network failure never reached
// the server at all" — the exact three categories the failure report asked
// to be able to distinguish, and never with any credential/token value.

let infoSpy: ReturnType<typeof vi.spyOn>;

beforeEach(() => {
  infoSpy = vi.spyOn(console, "info").mockImplementation(() => {});
  window.localStorage.clear();
});

function lastLoggedEntry(): Record<string, unknown> {
  const call = infoSpy.mock.calls.at(-1);
  expect(call?.[0]).toBe("[AUTH_DIAG]");
  return call?.[1] as Record<string, unknown>;
}

describe("recordLoginFailureDiagnostic", () => {
  it("categorises a 401 as invalid_credentials", () => {
    recordLoginFailureDiagnostic("native_login", new ApiError(401, "Invalid email or password."));
    expect(lastLoggedEntry()).toMatchObject({
      event: "LOGIN_FAILED",
      context: "native_login",
      category: "invalid_credentials",
      status: 401,
    });
  });

  it("categorises a 403 as invalid_credentials", () => {
    recordLoginFailureDiagnostic("native_login", new ApiError(403, "Forbidden"));
    expect(lastLoggedEntry()).toMatchObject({ category: "invalid_credentials", status: 403 });
  });

  it("categorises a 422 as invalid_credentials", () => {
    recordLoginFailureDiagnostic("native_login", new ApiError(422, "Validation error"));
    expect(lastLoggedEntry()).toMatchObject({ category: "invalid_credentials", status: 422 });
  });

  it("categorises a 500 as server_unavailable", () => {
    recordLoginFailureDiagnostic("native_login", new ApiError(500, "Internal Server Error"));
    expect(lastLoggedEntry()).toMatchObject({ category: "server_unavailable", status: 500 });
  });

  it("categorises a 503 as server_unavailable", () => {
    recordLoginFailureDiagnostic("native_login", new ApiError(503, "Service Unavailable"));
    expect(lastLoggedEntry()).toMatchObject({ category: "server_unavailable", status: 503 });
  });

  it("categorises an unexpected 4xx (e.g. a CORS-origin-rejection 403 from a different shape) as api_configuration_error", () => {
    recordLoginFailureDiagnostic("native_login", new ApiError(429, "Too many requests"));
    expect(lastLoggedEntry()).toMatchObject({ category: "api_configuration_error", status: 429 });
  });

  it("categorises a non-ApiError (fetch() itself rejected — e.g. a blocked CORS preflight) as network_or_cors_error, with no status", () => {
    recordLoginFailureDiagnostic("native_login", new TypeError("Failed to fetch"));
    const entry = lastLoggedEntry();
    expect(entry).toMatchObject({ category: "network_or_cors_error", message: "TypeError" });
    expect(entry.status).toBeUndefined();
  });

  it("never records the ApiError message or any credential value", () => {
    recordLoginFailureDiagnostic(
      "native_login",
      new ApiError(401, "wrong-password-was-hunter2"),
    );
    const entry = lastLoggedEntry();
    expect(JSON.stringify(entry)).not.toContain("hunter2");
  });
});
