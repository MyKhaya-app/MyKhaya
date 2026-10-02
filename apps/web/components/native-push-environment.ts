import { registerPlugin } from "@capacitor/core";
import { isNativeShell, nativePlatform } from "./native-runtime";

export type NativePushEnvironment = "sandbox" | "production";

interface NativePushEnvironmentPlugin {
  getEnvironment(): Promise<{ environment: NativePushEnvironment }>;
}

const NativePushEnvironmentPlugin = registerPlugin<NativePushEnvironmentPlugin>(
  "NativePushEnvironment",
);

/** Reads the signed iOS aps-environment entitlement through the native bridge. */
export async function nativePushEnvironment(): Promise<NativePushEnvironment> {
  if (!isNativeShell() || nativePlatform() !== "ios") {
    throw new Error("Native APNs environment is only available in the iOS shell");
  }
  const result = await NativePushEnvironmentPlugin.getEnvironment();
  if (result.environment !== "sandbox" && result.environment !== "production") {
    throw new Error("Native iOS APNs environment is invalid");
  }
  return result.environment;
}
