import { getApiBaseUrl } from "../config/apiConfig";

export type ApiHealthResult =
  | { status: "connected" }
  | { status: "unreachable"; message: string }
  | { status: "misconfigured"; message: string };

const REQUEST_TIMEOUT_MS = 5000;

/**
 * Calls the unauthenticated liveness endpoint only - proves the phone can
 * reach the API over the LAN. Does not touch auth/session state.
 */
export async function checkApiHealth(): Promise<ApiHealthResult> {
  let baseUrl: string;
  try {
    baseUrl = getApiBaseUrl();
  } catch (error) {
    return { status: "misconfigured", message: (error as Error).message };
  }

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    const response = await fetch(`${baseUrl}/api/v1/health/live`, {
      signal: controller.signal,
    });
    if (!response.ok) {
      return {
        status: "unreachable",
        message: `The MyKhaya API responded with an error (${response.status}).`,
      };
    }
    return { status: "connected" };
  } catch {
    return {
      status: "unreachable",
      message:
        "Couldn't reach the MyKhaya API. Check your phone and computer are on the same network and the backend is running.",
    };
  } finally {
    clearTimeout(timeout);
  }
}
