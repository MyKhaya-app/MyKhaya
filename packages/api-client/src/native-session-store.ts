/**
 * Storage abstraction for a native (bearer-transport, ADR 0010) session
 * token — deliberately separate from anything the browser/cookie client
 * uses. A native session is a single opaque string; per ADR 0010's
 * SecureStore requirements, nothing else (no CSRF value, no user profile
 * data) is ever stored alongside it here.
 *
 * There is intentionally no browser localStorage/sessionStorage
 * implementation in this file for production use — ADR 0010 requires the
 * eventual iOS Keychain accessibility class `WHEN_UNLOCKED_THIS_DEVICE_ONLY`
 * (excluded from iCloud sync/device-backup restore), which no browser
 * storage API can provide. Until a Capacitor Keychain adapter exists, the
 * only implementation shipped here is an in-memory one, safe for tests and
 * for any dev-only tooling that doesn't need the token to survive a
 * process restart.
 */

export interface NativeSession {
  /** The raw bearer token. Never logged, never placed in a URL, never
   * stored anywhere else in this object or elsewhere in the app. */
  token: string;
}

export interface NativeSessionStore {
  get(): Promise<NativeSession | null>;
  set(session: NativeSession): Promise<void>;
  /**
   * Implements ADR 0010's "compare-and-clear" 401 handling: only clears the
   * store if the token currently held still matches `token` (the token a
   * just-failed request actually used). If a rotation already replaced it
   * with a newer token since that request was sent, this is a deliberate
   * no-op — the newer token's validity is unaffected by a stale response
   * for the old one.
   */
  clearIfMatches(token: string): Promise<void>;
  clear(): Promise<void>;
}

/**
 * Safe default for tests and any dev-only usage. Do not use this for a real
 * native session in a shipped native app — the token is lost the moment the
 * process exits, which is fine for a test double but not a substitute for
 * the Keychain-backed store a Capacitor build must eventually provide.
 */
export class InMemoryNativeSessionStore implements NativeSessionStore {
  #session: NativeSession | null = null;

  async get(): Promise<NativeSession | null> {
    return this.#session;
  }

  async set(session: NativeSession): Promise<void> {
    this.#session = session;
  }

  async clearIfMatches(token: string): Promise<void> {
    if (this.#session?.token === token) {
      this.#session = null;
    }
  }

  async clear(): Promise<void> {
    this.#session = null;
  }
}
