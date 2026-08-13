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
