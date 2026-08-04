import { getApiBaseUrl } from "../config/apiConfig";
import { clientHeaders } from "../api/clientHeaders";
import { authorizedFetch } from "../api/authorizedFetch";
import { tokenStore } from "./tokenStore";

export class AuthError extends Error {}

export type SignedInUser = {
  id: string;
  email: string;
  displayName: string;
  emailVerified: boolean;
};

async function readErrorMessage(response: Response, fallback: string): Promise<string> {
  const body = (await response.json().catch(() => null)) as { detail?: string } | null;
  return body?.detail ?? fallback;
}

export async function login(email: string, password: string): Promise<SignedInUser> {
  const response = await fetch(`${getApiBaseUrl()}/api/v1/auth/mobile/login`, {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      ...clientHeaders(),
    },
    body: JSON.stringify({ email, password }),
  });
  if (!response.ok) {
    throw new AuthError(await readErrorMessage(response, "The email or password is not correct."));
  }
  const data = (await response.json()) as {
    id: string;
    email: string;
    display_name: string;
    email_verified: boolean;
    session_token: string;
  };
  await tokenStore.set(data.session_token);
  return {
    id: data.id,
    email: data.email,
    displayName: data.display_name,
    emailVerified: data.email_verified,
  };
}

export async function logout(): Promise<void> {
  try {
    await authorizedFetch("/api/v1/auth/mobile/logout", { method: "POST" });
  } catch {
    // Local sign-out must still happen if the network call fails - see ADR 0010.
  } finally {
    await tokenStore.clear();
  }
}

export async function isSignedIn(): Promise<boolean> {
  return (await tokenStore.get()) !== null;
}

/**
 * Not yet wired to any UI action or schedule - available for a future
 * session-refresh flow. If the app is killed between receiving the new
 * token and persisting it, the user is simply signed out and must sign in
 * again; that is the intended safe failure mode (see ADR 0010).
 */
export async function rotateSession(): Promise<void> {
  const response = await authorizedFetch("/api/v1/auth/mobile/sessions/rotate", {
    method: "POST",
  });
  if (!response.ok) {
    throw new AuthError(await readErrorMessage(response, "Could not refresh your session."));
  }
  const data = (await response.json()) as { session_token: string };
  await tokenStore.set(data.session_token);
}
