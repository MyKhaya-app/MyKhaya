import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

function readScript(): string {
  return readFileSync(fileURLToPath(new URL("../scripts/ensure-storyboard-scene-delegate.sh", import.meta.url)), "utf8");
}

describe("storyboard-owned SceneDelegate bootstrap", () => {
  it("removes competing programmatic bridge/window setup", () => {
    const script = readScript();
    expect(script).toContain("rootViewController = CAPBridgeViewController");
    expect(script).toContain("makeKeyAndVisible");
    expect(script).toContain("SceneDelegateProxy.shared.scene");
    expect(script).toContain("window property");
  });

  it("does not rewrite or remove the storyboard window property", () => {
    expect(readScript()).not.toContain("window = nil");
  });
});
