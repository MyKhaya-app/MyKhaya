import * as SecureStore from "expo-secure-store";

const SESSION_TOKEN_KEY = "mykhaya.session_token";

const OPTIONS: SecureStore.SecureStoreOptions = {
  keychainAccessible: SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY,
};

/**
 * The only place the raw bearer token touches storage. Never mirror this
 * value into AsyncStorage, app state that gets persisted, logs, analytics
 * or crash reports - see ADR 0010.
 */
export const tokenStore = {
  get: (): Promise<string | null> => SecureStore.getItemAsync(SESSION_TOKEN_KEY, OPTIONS),
  set: (token: string): Promise<void> => SecureStore.setItemAsync(SESSION_TOKEN_KEY, token, OPTIONS),
  clear: (): Promise<void> => SecureStore.deleteItemAsync(SESSION_TOKEN_KEY, OPTIONS),
};
