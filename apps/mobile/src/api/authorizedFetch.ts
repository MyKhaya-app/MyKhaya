import { getApiBaseUrl } from "../config/apiConfig";
import { tokenStore } from "../auth/tokenStore";
import { clientHeaders } from "./clientHeaders";

/**
 * Attaches the stored bearer token and, on a 401, clears it from
 * SecureStore only if it still matches the token this specific request
 * used. A stale 401 for a token that has since been replaced by rotation
 * must not delete the newer, still-valid token - see ADR 0010's
 * compare-and-clear requirement.
 */
export async function authorizedFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const baseUrl = getApiBaseUrl();
  const usedToken = await tokenStore.get();
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  if (init.body) headers.set("Content-Type", "application/json");
  if (usedToken) headers.set("Authorization", `Bearer ${usedToken}`);
  for (const [name, value] of Object.entries(clientHeaders())) headers.set(name, value);

  const response = await fetch(`${baseUrl}${path}`, { ...init, headers });

  if (response.status === 401 && usedToken) {
    const currentToken = await tokenStore.get();
    if (currentToken === usedToken) {
      await tokenStore.clear();
    }
  }
  return response;
}
