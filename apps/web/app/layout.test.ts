import { describe, expect, it } from "vitest";
import { metadataForSurface } from "./layout";

describe("root metadata by application surface", () => {
  it("keeps consumer PWA metadata on consumer surfaces", () => {
    const metadata = metadataForSurface(false);

    expect(metadata.manifest).toBe("/manifest.webmanifest");
    expect(metadata.appleWebApp).toEqual({ title: "MyKhaya", statusBarStyle: "default" });
    expect(metadata.icons).toEqual({ apple: "/images/mykhaya-apple-icon.png" });
  });

  it("omits consumer PWA metadata from the Platform Control Centre", () => {
    const metadata = metadataForSurface(true);

    expect(metadata.manifest).toBeUndefined();
    expect(metadata.appleWebApp).toBeUndefined();
    expect(metadata.icons).toBeUndefined();
    expect(metadata.title).toEqual({ default: "MyKhaya", template: "%s · MyKhaya" });
    expect(metadata.description).toBe("Your family's digital home");
  });
});
