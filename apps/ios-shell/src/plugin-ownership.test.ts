import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import packageJson from "../package.json";

function readJson(relativePath: string): { dependencies: Record<string, string> } {
  const path = fileURLToPath(new URL(relativePath, import.meta.url));
  return JSON.parse(readFileSync(path, "utf8"));
}

// Plugin ownership fix: `npx cap sync ios` discovers native Capacitor
// plugins from the package.json of the package it's run in
// (apps/ios-shell), not from apps/web's own dependencies — the live
// frontend (apps/web) is loaded remotely over HTTPS and is never bundled
// into the native project, so a plugin declared only there is invisible to
// Capacitor's native auto-linking. This was the confirmed root cause of
// the first physical-device TestFlight build's persistent-login (Keychain)
// and Quick Sign-In (biometric) failures — apps/ios-shell/package.json
// previously declared only @capacitor/core and @capacitor/ios.
//
// This test guards against that regressing silently: every native
// Capacitor plugin apps/web's components actually import at runtime
// (components/keychain-native-session-store.ts, native-biometric.ts,
// native-biometric-preference.ts, open-external-url.ts) must also be an
// explicit apps/ios-shell dependency, matched exactly (never rely on
// pnpm workspace hoisting to make a plugin "available").

const REQUIRED_NATIVE_PLUGINS = [
  "@aparajita/capacitor-biometric-auth",
  "@aparajita/capacitor-secure-storage",
  "@capacitor/app",
  "@capacitor/browser",
  "@capacitor/core",
  "@capacitor/ios",
  "@capacitor/push-notifications",
] as const;

describe("apps/ios-shell package.json — native plugin ownership", () => {
  it.each(REQUIRED_NATIVE_PLUGINS)("declares %s as its own dependency", (plugin) => {
    expect(packageJson.dependencies).toHaveProperty(plugin);
    expect(typeof (packageJson.dependencies as Record<string, string>)[plugin]).toBe("string");
  });

  it("matches apps/web's own plugin versions exactly, so both packages resolve the same native implementation", () => {
    const webPackageJson = readJson("../../web/package.json");
    for (const plugin of REQUIRED_NATIVE_PLUGINS) {
      if (plugin in webPackageJson.dependencies) {
        expect((packageJson.dependencies as Record<string, string>)[plugin]).toBe(
          webPackageJson.dependencies[plugin],
        );
      }
    }
  });
});
