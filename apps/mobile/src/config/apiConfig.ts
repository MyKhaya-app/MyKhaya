export class ApiConfigError extends Error {}

/**
 * A physical device can't reach this machine's "localhost", so the API base
 * URL must be supplied explicitly via EXPO_PUBLIC_API_BASE_URL (see
 * apps/mobile/.env.example). Fails loudly rather than silently falling back
 * to a guessed address.
 */
export function getApiBaseUrl(): string {
  const raw = process.env.EXPO_PUBLIC_API_BASE_URL;
  if (!raw) {
    throw new ApiConfigError(
      "EXPO_PUBLIC_API_BASE_URL is not set. Copy apps/mobile/.env.example to .env and set it to your development machine's LAN address.",
    );
  }
  let parsed: URL;
  try {
    parsed = new URL(raw);
  } catch {
    throw new ApiConfigError(`EXPO_PUBLIC_API_BASE_URL is not a valid URL: "${raw}"`);
  }
  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
    throw new ApiConfigError(`EXPO_PUBLIC_API_BASE_URL must use http or https: "${raw}"`);
  }
  return raw.replace(/\/+$/, "");
}
