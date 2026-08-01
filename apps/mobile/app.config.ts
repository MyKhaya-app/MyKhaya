import type { ExpoConfig } from "expo/config";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

function readVersion(): string {
  const filePath = resolve(__dirname, "..", "..", "VERSION");
  return readFileSync(filePath, "utf-8").trim();
}

function stableVersion(version: string): string {
  const [base] = version.split("-");
  return base;
}

const appVersion = readVersion();

const config: ExpoConfig = {
  name: "MyKhaya",
  slug: "mykhaya",
  version: stableVersion(appVersion),
  scheme: "mykhaya",
  orientation: "portrait",
  userInterfaceStyle: "light",
  plugins: ["expo-router", "expo-secure-store"],
  experiments: { typedRoutes: true },
  ios: { supportsTablet: true, bundleIdentifier: "app.mykhaya.mobile" },
  android: { package: "app.mykhaya.mobile" },
  extra: {
    mykhayaVersion: appVersion,
  },
};

export default config;
