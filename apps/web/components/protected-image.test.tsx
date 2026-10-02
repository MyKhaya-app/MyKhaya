import { describe, expect, it } from "vitest";
import { apiRelativeMediaPath, browserMediaPath } from "./protected-image";

describe("protected media URL contract", () => {
  it("keeps API-relative paths relative for native transport", () => {
    expect(apiRelativeMediaPath("/homes/h1/meals/images/image.webp")).toBe(
      "/homes/h1/meals/images/image.webp",
    );
    expect(apiRelativeMediaPath("/api/v1/homes/h1/meals/images/image.webp")).toBe(
      "/homes/h1/meals/images/image.webp",
    );
  });

  it("adds the API prefix once for browser cookie transport", () => {
    expect(browserMediaPath("/homes/h1/meals/images/image.webp")).toBe(
      "/api/v1/homes/h1/meals/images/image.webp",
    );
    expect(browserMediaPath("/api/v1/homes/h1/meals/images/image.webp")).toBe(
      "/api/v1/homes/h1/meals/images/image.webp",
    );
  });
});
