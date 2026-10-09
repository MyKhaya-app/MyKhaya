import { spawnSync } from "node:child_process";
import { existsSync, readdirSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { IOS_APP_ENVIRONMENTS, type IosAppEnvironment } from "./config";

// DEV and PROD are two separate iOS apps built from one Xcode project. These
// tests check every committed native file against the agreed matrix
// (IOS_APP_ENVIRONMENTS, docs/mobile/ios-environments.md) on any OS, so a
// change like commit fb3e1b2 (PROD identifiers written into shared files,
// which crashed the DEV app) fails here instead of on a phone.
// scripts/validate-ios-environments.sh repeats the check on a Mac against
// the values Xcode actually expands.

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const read = (path: string) => readFileSync(join(ROOT, path), "utf8").replace(/\r\n/g, "\n");
const ENVIRONMENTS = Object.values(IOS_APP_ENVIRONMENTS);
const CONFIGURATIONS = ENVIRONMENTS.flatMap((app) =>
  (["Debug", "Release"] as const).map((flavour) => ({ name: `${flavour}-${app.configurationSuffix}`, flavour, app })),
);

// ---- minimal OpenStep (old-style) plist parser for project.pbxproj ---------

type PlistValue = string | PlistValue[] | { [key: string]: PlistValue };

function parsePbxproj(text: string): Record<string, PlistValue> {
  let i = 0;
  const skip = () => {
    for (;;) {
      while (i < text.length && /\s/.test(text[i]!)) i++;
      if (text.startsWith("//", i)) i = text.indexOf("\n", i) + 1 || text.length;
      else if (text.startsWith("/*", i)) i = text.indexOf("*/", i) + 2;
      else return;
    }
  };
  const value = (): PlistValue => {
    skip();
    const c = text[i];
    if (c === "{") {
      i++;
      const dict: Record<string, PlistValue> = {};
      for (skip(); text[i] !== "}"; skip()) {
        const key = value() as string;
        skip();
        expect(text[i], `"=" after ${key}`).toBe("=");
        i++;
        dict[key] = value();
        skip();
        expect(text[i], `";" after ${key}`).toBe(";");
        i++;
      }
      i++;
      return dict;
    }
    if (c === "(") {
      i++;
      const array: PlistValue[] = [];
      for (skip(); text[i] !== ")"; skip()) {
        array.push(value());
        skip();
        if (text[i] === ",") i++;
      }
      i++;
      return array;
    }
    if (c === '"') {
      let out = "";
      for (i++; text[i] !== '"'; i++) out += text[i] === "\\" ? text[++i] : text[i];
      i++;
      return out;
    }
    const token = /^[^\s;,=(){}"]+/.exec(text.slice(i))?.[0];
    expect(token, `token at ${i}`).toBeTruthy();
    i += token!.length;
    return token!;
  };
  const root = value() as Record<string, PlistValue>;
  return root.objects as Record<string, PlistValue>;
}

type PbxObject = Record<string, PlistValue> & { isa: string };
const objects = parsePbxproj(read("ios/App/App.xcodeproj/project.pbxproj")) as Record<string, PbxObject>;
const byIsa = (isa: string) => Object.entries(objects).filter(([, o]) => o.isa === isa);
const target = (name: string) => byIsa("PBXNativeTarget").find(([, o]) => o.name === name)![1];
const project = byIsa("PBXProject")[0]![1];
const configurations = (listId: string) =>
  (objects[listId]!.buildConfigurations as string[]).map((id) => ({ ...objects[id]!, id }) as PbxObject);
const settingsOf = (config: PbxObject) => config.buildSettings as Record<string, string>;

// ---- xcconfig + plist helpers ------------------------------------------------

function xcconfig(relativePath: string): Record<string, string> {
  const settings: Record<string, string> = {};
  for (const line of read(relativePath).split("\n")) {
    const include = /^#include "(.+)"/.exec(line);
    if (include) {
      Object.assign(settings, xcconfig(join(dirname(relativePath), include[1]!)));
      continue;
    }
    const setting = /^([A-Z0-9_]+)\s*=\s*(.*?)\s*$/.exec(line.replace(/\/\/.*$/, ""));
    if (setting) settings[setting[1]!] = setting[2]!;
  }
  return settings;
}

function expand(value: string, settings: Record<string, string>): string {
  return value.replace(/\$\(([A-Z0-9_]+)\)/g, (_, name: string) =>
    name === "inherited" ? "" : expand(settings[name] ?? "", settings),
  );
}

/** Xcode's precedence, simplified: target > project > project xcconfig. */
function resolved(targetName: string, configurationName: string): Record<string, string> {
  const projectConfig = configurations(project.buildConfigurationList as string).find(
    (c) => c.name === configurationName,
  )!;
  const targetConfig = configurations(target(targetName).buildConfigurationList as string).find(
    (c) => c.name === configurationName,
  )!;
  const fileRef = objects[projectConfig.baseConfigurationReference as string]!;
  return {
    ...xcconfig(`ios/App/Config/${fileRef.path as string}`),
    ...settingsOf(projectConfig),
    ...settingsOf(targetConfig),
  };
}

function plistString(xml: string, key: string): string | undefined {
  return new RegExp(`<key>${key}</key>\\s*<string>([^<]*)</string>`).exec(xml)?.[1];
}

function appGroups(xml: string): string[] {
  const block = /<key>com\.apple\.security\.application-groups<\/key>\s*<array>([\s\S]*?)<\/array>/.exec(xml)?.[1];
  return [...(block ?? "").matchAll(/<string>([^<]*)<\/string>/g)].map((m) => m[1]!);
}

const stripComments = (code: string, line: RegExp) =>
  code.replace(/\/\*[\s\S]*?\*\//g, "").split("\n").filter((l) => !line.test(l)).map((l) => l.replace(/\s\/\/.*$/, "")).join("\n");

// ---- the matrix itself --------------------------------------------------------

describe("the agreed DEV/PROD matrix", () => {
  it("keeps the existing identifiers", () => {
    expect(IOS_APP_ENVIRONMENTS.development).toMatchObject({
      bundleId: "app.mykhaya.mobile",
      widgetBundleId: "app.mykhaya.mobile.widgets",
      appGroup: "group.app.mykhaya.mobile",
      urlScheme: "mykhaya",
      serverHost: "dev.mykhaya.app",
    });
    expect(IOS_APP_ENVIRONMENTS.production).toMatchObject({
      bundleId: "app.mykhaya.mobile.prod",
      widgetBundleId: "app.mykhaya.mobile.prod.widgets",
      appGroup: "group.app.mykhaya.mobile.prod",
      urlScheme: "mykhaya-prod",
      serverHost: "mykhaya.app",
    });
  });

  it("gives the two apps nothing in common that iOS requires to be unique", () => {
    const [dev, prod] = [IOS_APP_ENVIRONMENTS.development, IOS_APP_ENVIRONMENTS.production];
    for (const key of ["bundleId", "widgetBundleId", "appGroup", "urlScheme", "serverHost", "scheme", "displayName"] as const) {
      expect(dev[key], key).not.toBe(prod[key]);
    }
    for (const app of ENVIRONMENTS) {
      expect(app.widgetBundleId).toBe(`${app.bundleId}.widgets`);
      expect(app.appGroup).toBe(`group.${app.bundleId}`);
    }
  });
});

// ---- Xcode build configurations ------------------------------------------------

describe("Xcode build configurations", () => {
  const names = CONFIGURATIONS.map((c) => c.name).sort();

  it.each(["App", "MyKhayaWidgets"])("%s has exactly the four DEV/PROD configurations", (name) => {
    const list = objects[target(name).buildConfigurationList as string]!;
    expect(configurations(target(name).buildConfigurationList as string).map((c) => c.name).sort()).toEqual(names);
    expect(list.defaultConfigurationName).toBe("Release-Dev");
  });

  it("each project-level configuration is based on its own xcconfig; targets add none", () => {
    for (const config of configurations(project.buildConfigurationList as string)) {
      const fileRef = objects[config.baseConfigurationReference as string];
      expect(fileRef?.path, config.name as string).toBe(`${config.name as string}.xcconfig`);
    }
    for (const name of ["App", "MyKhayaWidgets"]) {
      for (const config of configurations(target(name).buildConfigurationList as string)) {
        expect(config.baseConfigurationReference, `${name} ${config.name as string}`).toBeUndefined();
      }
    }
  });

  it("targets never override an environment value (no literals left to drift)", () => {
    for (const name of ["App", "MyKhayaWidgets"]) {
      for (const config of configurations(target(name).buildConfigurationList as string)) {
        const settings = settingsOf(config);
        for (const key of Object.keys(settings)) {
          expect(key.startsWith("MYKHAYA_"), `${name} ${config.name as string} sets ${key}`).toBe(false);
        }
        expect(settings.DEVELOPMENT_TEAM).toBeUndefined();
        expect(settings.CODE_SIGN_STYLE).toBeUndefined();
      }
    }
  });

  it.each(CONFIGURATIONS)("$name resolves to the $app.environment identity", ({ name, flavour, app }) => {
    const appSettings = resolved("App", name);
    const widgetSettings = resolved("MyKhayaWidgets", name);
    expect(expand(appSettings.PRODUCT_BUNDLE_IDENTIFIER!, appSettings)).toBe(app.bundleId);
    expect(expand(widgetSettings.PRODUCT_BUNDLE_IDENTIFIER!, widgetSettings)).toBe(app.widgetBundleId);
    for (const settings of [appSettings, widgetSettings]) {
      expect(settings.MYKHAYA_ENVIRONMENT).toBe(app.environment);
      expect(settings.MYKHAYA_APP_GROUP).toBe(app.appGroup);
      expect(settings.MYKHAYA_URL_SCHEME).toBe(app.urlScheme);
      expect(settings.MYKHAYA_SERVER_HOST).toBe(app.serverHost);
      expect(settings.MYKHAYA_DISPLAY_NAME).toBe(app.displayName);
      expect(settings.DEVELOPMENT_TEAM).toBe("M86392YDLQ");
      expect(settings.CODE_SIGN_STYLE).toBe("Automatic");
      expect(settings.MYKHAYA_APNS_BUILD_ENVIRONMENT).toBe(flavour === "Debug" ? "development" : "production");
    }
    expect(expand(appSettings.INFOPLIST_KEY_CFBundleDisplayName!, appSettings)).toBe(app.displayName);
    expect(appSettings.CODE_SIGN_ENTITLEMENTS).toBe(`App/App${flavour}.entitlements`);
    if (flavour === "Debug") expect(appSettings.CAPACITOR_DEBUG).toBe("true");
  });

  it.each(["App", "MyKhayaWidgets"])("%s runs the environment check before compiling", (name) => {
    const [firstPhase] = target(name).buildPhases as string[];
    const phase = objects[firstPhase!]!;
    expect(phase.isa).toBe("PBXShellScriptBuildPhase");
    expect(phase.shellScript).toContain("scripts/validate-ios-environments.sh\" --build-phase");
  });
});

// ---- entitlements, Info.plists, schemes -------------------------------------

describe("entitlements and Info.plists take every environment value from the build", () => {
  it.each(["ios/App/App/AppDebug.entitlements", "ios/App/App/AppRelease.entitlements", "native/widgets/MyKhayaWidgets.entitlements"])(
    "%s lists only $(MYKHAYA_APP_GROUP)",
    (path) => {
      expect(appGroups(read(path))).toEqual(["$(MYKHAYA_APP_GROUP)"]);
    },
  );

  it("keeps APNs on the main app only, from the build configuration", () => {
    for (const path of ["ios/App/App/AppDebug.entitlements", "ios/App/App/AppRelease.entitlements"]) {
      expect(plistString(read(path), "aps-environment")).toBe("$(MYKHAYA_APNS_BUILD_ENVIRONMENT)");
    }
    expect(read("native/widgets/MyKhayaWidgets.entitlements")).not.toContain("aps-environment");
  });

  it("the app registers only its own widget URL scheme and knows its environment", () => {
    const info = read("ios/App/App/Info.plist");
    const urlTypes = /<key>CFBundleURLTypes<\/key>\s*<array>([\s\S]*?)<\/array>\s*<key>/.exec(info)![1]!;
    expect([...urlTypes.matchAll(/<key>CFBundleURLSchemes<\/key>\s*<array>\s*<string>([^<]*)<\/string>\s*<\/array>/g)].map((m) => m[1])).toEqual([
      "$(MYKHAYA_URL_SCHEME)",
    ]);
    expect(plistString(urlTypes, "CFBundleURLName")).toBe("$(PRODUCT_BUNDLE_IDENTIFIER).widgets");
    expect(plistString(info, "CFBundleDisplayName")).toBe("$(MYKHAYA_DISPLAY_NAME)");
    expect(plistString(info, "MyKhayaEnvironment")).toBe("$(MYKHAYA_ENVIRONMENT)");
    expect(plistString(info, "MyKhayaServerHost")).toBe("$(MYKHAYA_SERVER_HOST)");
    expect(plistString(info, "MyKhayaURLScheme")).toBe("$(MYKHAYA_URL_SCHEME)");
    expect(plistString(info, "MyKhayaAppGroup")).toBe("$(MYKHAYA_APP_GROUP)");
  });

  it("the widget knows its environment, scheme and App Group (and has no server)", () => {
    const info = read("native/widgets/Info.plist");
    expect(plistString(info, "MyKhayaEnvironment")).toBe("$(MYKHAYA_ENVIRONMENT)");
    expect(plistString(info, "MyKhayaURLScheme")).toBe("$(MYKHAYA_URL_SCHEME)");
    expect(plistString(info, "MyKhayaAppGroup")).toBe("$(MYKHAYA_APP_GROUP)");
    expect(plistString(info, "MyKhayaServerHost")).toBeUndefined();
    expect(plistString(info, "CFBundleIdentifier")).toBe("$(PRODUCT_BUNDLE_IDENTIFIER)");
  });

  it("has exactly one Run/Archive scheme pair per environment, never crossing environments", () => {
    const dir = "ios/App/App.xcodeproj/xcshareddata/xcschemes";
    const expected = ENVIRONMENTS.flatMap((app) => [app.scheme, app.widgetScheme]).sort();
    expect(readdirSync(join(ROOT, dir)).map((f) => f.replace(/\.xcscheme$/, "")).sort()).toEqual(expected);
    for (const app of ENVIRONMENTS) {
      for (const [scheme, blueprint] of [[app.scheme, "App"], [app.widgetScheme, "MyKhayaWidgets"]] as const) {
        const xml = read(`${dir}/${scheme}.xcscheme`);
        const used = [...new Set([...xml.matchAll(/buildConfiguration = "([^"]+)"/g)].map((m) => m[1]))].sort();
        expect(used, scheme).toEqual([`Debug-${app.configurationSuffix}`, `Release-${app.configurationSuffix}`]);
        expect(/<LaunchAction\s+buildConfiguration = "([^"]+)"/.exec(xml)![1]).toBe(`Debug-${app.configurationSuffix}`);
        expect(/<ArchiveAction\s+buildConfiguration = "([^"]+)"/.exec(xml)![1]).toBe(`Release-${app.configurationSuffix}`);
        expect(xml).toContain(`BlueprintName = "${blueprint}"`);
      }
    }
  });
});

// ---- no hardcoded environment in shared code or scripts ----------------------

const IDENTIFIER_LITERALS = [/app\.mykhaya\.mobile/, /group\.app\.mykhaya/, /mykhaya-prod/, /"mykhaya"/, /mykhaya\.app/];

function swiftFiles(dir: string): string[] {
  return readdirSync(join(ROOT, dir), { withFileTypes: true }).flatMap((entry) =>
    entry.isDirectory() ? swiftFiles(join(dir, entry.name)) : entry.name.endsWith(".swift") ? [join(dir, entry.name)] : [],
  );
}

describe("no environment is hardcoded in shared native code or setup scripts", () => {
  const nativeSources = [...swiftFiles("native/WidgetCore/Sources"), ...swiftFiles("native/widgets"), ...swiftFiles("native/plugin"), ...swiftFiles("ios/App/App")];

  it.each(nativeSources)("%s", (path) => {
    const code = stripComments(read(path), /^\s*\/\//);
    for (const literal of IDENTIFIER_LITERALS) expect(code, `${path} contains ${literal}`).not.toMatch(literal);
  });

  it.each([
    "scripts/setup-widget-extension.rb",
    "scripts/ensure-widget-schemes.rb",
    "scripts/link-widget-core-package.rb",
    "scripts/add-app-target-sources.rb",
    "scripts/install-widget-sources.sh",
  ])("%s", (path) => {
    const code = stripComments(read(path), /^\s*#/);
    for (const literal of IDENTIFIER_LITERALS) expect(code, `${path} contains ${literal}`).not.toMatch(literal);
  });

  it("the main-app plugin sources and their installed copies are identical", () => {
    for (const file of readdirSync(join(ROOT, "native/plugin"))) {
      expect(read(`ios/App/App/${file}`), file).toBe(read(`native/plugin/${file}`));
    }
  });

  it("the widget deep-link code and the app's tap handler both use the configured scheme", () => {
    const deepLink = read("native/widgets/Shared/DeepLink.swift");
    expect(deepLink).toContain("MyKhayaEnvironment.current?.urlScheme");
    expect(deepLink).toContain("WidgetDeepLinkRoute.url(forPath: path, scheme: scheme)");
    const plugin = read("native/plugin/WidgetBridgePlugin.swift");
    expect(plugin).toContain("WidgetDeepLinkRoute.path(from: url, expectedScheme: scheme)");
    expect(read("native/plugin/MainViewController.swift")).toContain("descriptor.serverURL = serverURL.absoluteString");
  });
});

// ---- the Mac-side validator agrees with this matrix ------------------------

describe("scripts/validate-ios-environments.sh", () => {
  const script = read("scripts/validate-ios-environments.sh");

  it.each(ENVIRONMENTS)("encodes the same $environment values", (app: IosAppEnvironment) => {
    const line = script.split("\n").find((l) => l.includes(`env=${app.environment};`))!;
    const next = script.split("\n")[script.split("\n").indexOf(line) + 1]!;
    expect(`${line} ${next}`).toContain(`bundle=${app.bundleId};`);
    expect(`${line} ${next}`).toContain(`group=${app.appGroup}`);
    expect(`${line} ${next}`).toContain(`url_scheme=${app.urlScheme};`);
    expect(`${line} ${next}`).toContain(`host=${app.serverHost};`);
    expect(`${line} ${next}`).toContain(`display=${app.displayName} `);
  });

  it("mac-bootstrap.sh builds and launches the right app for each environment", () => {
    const bootstrap = read("scripts/mac-bootstrap.sh");
    for (const app of ENVIRONMENTS) {
      expect(bootstrap).toContain(
        `${app.environment}) SCHEME="${app.scheme}"; CONFIGURATION="Debug-${app.configurationSuffix}"; BUNDLE_ID="${app.bundleId}" ;;`,
      );
    }
    expect(bootstrap).toContain("sh scripts/validate-ios-environments.sh");
    expect(bootstrap).not.toMatch(/-scheme App\b/);
  });

  const shell = spawnSync("sh", ["-c", "exit 0"]).status === 0;

  function buildPhase(configuration: string, kind: "app" | "appex", overrides: Partial<Record<string, string>> = {}) {
    const app = CONFIGURATIONS.find((c) => c.name === configuration)!;
    const settings = resolved(kind === "app" ? "App" : "MyKhayaWidgets", configuration);
    const env = {
      ...process.env,
      CONFIGURATION: configuration,
      WRAPPER_EXTENSION: kind,
      TARGET_NAME: kind === "app" ? "App" : "MyKhayaWidgets",
      MYKHAYA_ENVIRONMENT: settings.MYKHAYA_ENVIRONMENT,
      MYKHAYA_APP_BUNDLE_ID: settings.MYKHAYA_APP_BUNDLE_ID,
      MYKHAYA_APP_GROUP: settings.MYKHAYA_APP_GROUP,
      MYKHAYA_URL_SCHEME: settings.MYKHAYA_URL_SCHEME,
      MYKHAYA_SERVER_HOST: settings.MYKHAYA_SERVER_HOST,
      MYKHAYA_DISPLAY_NAME: settings.MYKHAYA_DISPLAY_NAME,
      MYKHAYA_APNS_BUILD_ENVIRONMENT: settings.MYKHAYA_APNS_BUILD_ENVIRONMENT,
      PRODUCT_BUNDLE_IDENTIFIER: expand(settings.PRODUCT_BUNDLE_IDENTIFIER!, settings),
      ...overrides,
    };
    expect(app).toBeTruthy();
    return spawnSync("sh", [join(ROOT, "scripts/validate-ios-environments.sh"), "--build-phase"], { env, encoding: "utf8" });
  }

  it.skipIf(!shell).each(CONFIGURATIONS.map((c) => c.name))("build phase accepts the committed %s settings", (configuration) => {
    expect(buildPhase(configuration, "app").status).toBe(0);
    expect(buildPhase(configuration, "appex").status).toBe(0);
  });

  it.skipIf(!shell)("build phase fails a DEV build carrying any PROD value, and the reverse", () => {
    const dev = IOS_APP_ENVIRONMENTS.development;
    const prod = IOS_APP_ENVIRONMENTS.production;
    const crossed: [string, Record<string, string>][] = [
      ["Debug-Dev", { MYKHAYA_APP_GROUP: prod.appGroup }],
      ["Debug-Dev", { MYKHAYA_URL_SCHEME: prod.urlScheme }],
      ["Debug-Dev", { MYKHAYA_SERVER_HOST: prod.serverHost }],
      ["Release-Dev", { PRODUCT_BUNDLE_IDENTIFIER: prod.bundleId }],
      ["Debug-Prod", { MYKHAYA_APP_GROUP: dev.appGroup }],
      ["Release-Prod", { MYKHAYA_SERVER_HOST: dev.serverHost }],
      ["Release-Prod", { MYKHAYA_APNS_BUILD_ENVIRONMENT: "development" }],
      ["Debug", {}],
    ];
    for (const [configuration, overrides] of crossed) {
      const result = buildPhase(configuration === "Debug" ? "Debug-Dev" : configuration, "app", {
        ...overrides,
        ...(configuration === "Debug" ? { CONFIGURATION: "Debug" } : {}),
      });
      expect(result.status, `${configuration} ${JSON.stringify(overrides)}`).toBe(1);
      expect(result.stderr).toContain("MyKhaya iOS environment");
    }
    const widgetWithAppId = buildPhase("Debug-Prod", "appex", { PRODUCT_BUNDLE_IDENTIFIER: prod.bundleId });
    expect(widgetWithAppId.status).toBe(1);
  });
});

it("the committed project has no leftover generic Debug/Release configuration names", () => {
  for (const [, config] of byIsa("XCBuildConfiguration")) {
    expect(["Debug", "Release"]).not.toContain(config.name);
  }
  expect(existsSync(join(ROOT, "ios/App/Config/Environment-Dev.xcconfig"))).toBe(true);
});
