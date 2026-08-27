import {
  KeychainAccess,
  SecureStorage,
  StorageError,
} from "@aparajita/capacitor-secure-storage";
import type { NativeSession, NativeSessionStore } from "@mykhaya/api-client";

// The production iOS implementation of NativeSessionStore (task §9/§10 —
// Phase 3 deliberately shipped only InMemoryNativeSessionStore). Backed by
// @aparajita/capacitor-secure-storage, which stores directly in the iOS
// Keychain via Apple's own Keychain Services accessibility constants —
// chosen over @atroo/capacitor-secure-storage-plugin (which wraps a
// third-party SwiftKeychainWrapper dependency and has no publicly linked
// source for this scope, making it harder to audit) after comparing both.
//
// Every call below passes `sync: false` and (for `set`) an explicit
// `access` on the call itself, rather than relying on the plugin's global
// `setSynchronize()`/`setDefaultKeychainAccess()` state — so this store's
// security properties hold even if something else in the app ever changes
// that global state. This is what satisfies every one of ADR 0010/this
// phase's storage requirements:
//   - real iOS Keychain storage (not a JS-side fallback of any kind)
//   - KeychainAccess.whenUnlockedThisDeviceOnly on every write
//     (Apple's kSecAttrAccessibleWhenUnlockedThisDeviceOnly)
//   - sync: false on every call — never synced via iCloud Keychain
//   - throws (StorageError) rather than silently degrading to an insecure
//     fallback if the OS-level Keychain call itself fails
const KEY = "mykhaya.native.session.token";

export class KeychainNativeSessionStore implements NativeSessionStore {
  async get(): Promise<NativeSession | null> {
    let token: unknown;
    try {
      token = await SecureStorage.get(KEY, false, false);
    } catch (error) {
      if (error instanceof StorageError) return null;
      throw error;
    }
    if (typeof token !== "string" || token === "") return null;
    return { token };
  }

  async set(session: NativeSession): Promise<void> {
    await SecureStorage.set(
      KEY,
      session.token,
      false,
      false,
      KeychainAccess.whenUnlockedThisDeviceOnly,
    );
  }

  async clearIfMatches(token: string): Promise<void> {
    const current = await this.get();
    if (current?.token === token) {
      await this.clear();
    }
  }

  async clear(): Promise<void> {
    try {
      await SecureStorage.remove(KEY, false);
    } catch (error) {
      if (!(error instanceof StorageError)) throw error;
    }
  }
}
