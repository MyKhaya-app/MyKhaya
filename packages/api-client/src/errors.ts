/**
 * Shared response→ApiError parsing, factored out so the native transport
 * (native-client.ts) can reuse the exact same error-shape handling as the
 * browser client without either duplicating subtly-different logic or
 * requiring any change to `MyKhayaClient.request()` itself — the browser
 * client's own inline copy of this logic is left exactly as it was
 * (untouched) so its behaviour cannot drift by way of this refactor.
 */
export async function parseApiResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as { detail?: unknown } | null;
    const detail = body?.detail;
    if (detail && typeof detail === "object" && "message" in detail) {
      const { code, message, ...metadata } = detail as {
        code?: string;
        message: string;
        [key: string]: unknown;
      };
      throw new ApiError(response.status, message, code, metadata);
    }
    throw new ApiError(
      response.status,
      typeof detail === "string" ? detail : "Something went wrong. Please try again.",
    );
  }
  return response.status === 204 ? (undefined as T) : (response.json() as Promise<T>);
}

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
    // Populated only for the structured commercial-restriction error shape
    // (mykhaya.entitlements.commercial_restriction_error) — a stable,
    // provider-neutral code plus safe metadata (e.g. entitlement key,
    // numeric limit) so calling code can branch without parsing message
    // text. Absent for every other error, which stays a plain string
    // `detail` exactly as before — this is additive, not a breaking change.
    public readonly code?: string,
    public readonly metadata?: Record<string, unknown>,
  ) {
    super(message);
    this.name = "ApiError";
  }
}
