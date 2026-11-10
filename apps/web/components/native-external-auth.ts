import { registerPlugin } from "@capacitor/core";

export type NativeProviderAssertion = {
  identity_token: string;
  email?: string;
  display_name?: string;
};

type NativeExternalAuthPlugin = {
  signInApple(options: { nonce: string }): Promise<NativeProviderAssertion>;
  signInGoogle(options: { nonce: string; client_id: string }): Promise<NativeProviderAssertion>;
};

/** Native provider SDK boundary. Provider assertions are returned only to the
 * bearer-auth client for immediate API verification; this module never stores
 * them and never writes them to logs. Android Google/Apple and iOS Google
 * implementations must register the same closed plugin contract. */
export const NativeExternalAuth = registerPlugin<NativeExternalAuthPlugin>("NativeExternalAuth");
