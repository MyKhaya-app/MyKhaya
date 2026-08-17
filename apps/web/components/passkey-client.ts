import { startAuthentication, startRegistration } from "@simplewebauthn/browser";

export function passkeysSupported() {
  return (
    typeof window !== "undefined" &&
    typeof window.PublicKeyCredential !== "undefined" &&
    typeof navigator.credentials?.get === "function" &&
    typeof navigator.credentials?.create === "function"
  );
}

export async function createPasskey(optionsJson: string) {
  type RegistrationOptions = Parameters<typeof startRegistration>[0]["optionsJSON"];
  return startRegistration({ optionsJSON: JSON.parse(optionsJson) as RegistrationOptions });
}

export async function authenticateWithPasskey(optionsJson: string) {
  type AuthenticationOptions = Parameters<typeof startAuthentication>[0]["optionsJSON"];
  return startAuthentication({ optionsJSON: JSON.parse(optionsJson) as AuthenticationOptions });
}

export function passkeyWasCancelled(error: unknown) {
  return error instanceof DOMException && error.name === "NotAllowedError";
}
