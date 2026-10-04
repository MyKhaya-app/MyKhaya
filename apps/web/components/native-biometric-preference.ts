import { SecureStorage, StorageError } from "@aparajita/capacitor-secure-storage";

// Whether the user has turned on Quick Sign-In (Face ID/Touch ID) on this
// device — a UI preference, not a secret, but kept in the same Keychain-
// backed store the session credential already uses (see
// components/keychain-native-session-store.ts) rather than introducing a
// second storage mechanism for one boolean. Deliberately its own key/module:
// this flag's lifecycle (survives logout? — no, see native-auth.ts's
// nativeLogout) is independent of the session/device tokens' own.
const KEY = "mykhaya.native.biometric.enabled";
const DECLINED_KEY = "mykhaya.native.biometric.declined";

export type NativeBiometricPreference = "enabled" | "declined" | "undecided";

export async function getBiometricPreference(): Promise<NativeBiometricPreference> {
  if (await isBiometricSignInEnabled()) return "enabled";
  try {
    return (await SecureStorage.get(DECLINED_KEY, false, false)) === true
      ? "declined"
      : "undecided";
  } catch (error) {
    if (error instanceof StorageError) return "undecided";
    throw error;
  }
}

export async function isBiometricSignInEnabled(): Promise<boolean> {
  try {
    return (await SecureStorage.get(KEY, false, false)) === true;
  } catch (error) {
    if (error instanceof StorageError) return false;
    throw error;
  }
}

export async function setBiometricSignInEnabled(enabled: boolean): Promise<void> {
  if (enabled) {
    await SecureStorage.set(KEY, true, false, false);
    await SecureStorage.remove(DECLINED_KEY, false);
    return;
  }
  try {
    await SecureStorage.remove(KEY, false);
  } catch (error) {
    if (!(error instanceof StorageError)) throw error;
  }
}

export async function declineBiometricSignIn(): Promise<void> {
  try {
    await SecureStorage.set(DECLINED_KEY, true, false, false);
  } catch (error) {
    if (!(error instanceof StorageError)) throw error;
  }
}
