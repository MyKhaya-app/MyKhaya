import { afterEach, describe, expect, it, vi } from "vitest";
import { normalizeAvatarFile } from "./avatar-upload";

describe("normalizeAvatarFile", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("leaves ordinary supported images unchanged", async () => {
    const file = new File(["jpeg"], "photo.jpg", { type: "image/jpeg" });
    await expect(normalizeAvatarFile(file)).resolves.toBe(file);
  });

  it("recognises HEIC by filename when iOS omits the MIME type", async () => {
    const file = new File(["heic"], "IMG_1234.HEIC", { type: "" });
    await expect(normalizeAvatarFile(file)).resolves.toBe(file);
  });

  it("falls back to the original HEIF bytes when the browser cannot decode them", async () => {
    const file = new File(["heif"], "photo.heif", { type: "image/heif" });
    await expect(normalizeAvatarFile(file)).resolves.toBe(file);
  });

  it("normalises a decodable HEIC source to a metadata-free JPEG upload", async () => {
    const close = vi.fn();
    vi.stubGlobal(
      "createImageBitmap",
      vi.fn().mockResolvedValue({ width: 4000, height: 3000, close }),
    );
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({
      drawImage: vi.fn(),
    } as unknown as CanvasRenderingContext2D);
    vi.spyOn(HTMLCanvasElement.prototype, "toBlob").mockImplementation((callback) => {
      callback(new Blob(["jpeg"], { type: "image/jpeg" }));
    });

    const result = await normalizeAvatarFile(
      new File(["heic"], "IMG_1234.HEIC", { type: "image/heic" }),
    );

    expect(result.name).toBe("IMG_1234.jpg");
    expect(result.type).toBe("image/jpeg");
    expect(close).toHaveBeenCalledOnce();
  });
});
