import { describe, expect, it } from "vitest";
import { GET } from "./route";

describe("consumer web manifest route", () => {
  it("returns the consumer manifest with the manifest content type", async () => {
    const response = GET();

    expect(response.headers.get("content-type")).toBe("application/manifest+json");
    expect(await response.json()).toMatchObject({
      name: "MyKhaya — Your family's digital home",
      start_url: "/home",
      display: "standalone",
    });
  });
});
