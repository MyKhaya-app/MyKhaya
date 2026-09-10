import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@capacitor/core", () => ({
  Capacitor: {
    isNativePlatform: vi.fn().mockReturnValue(false),
    getPlatform: vi.fn().mockReturnValue("web"),
  },
}));

import {
  AvatarProcessingError,
  isImageFormatRejection,
  normalizeAvatarFile,
} from "./avatar-upload";

describe("normalizeAvatarFile", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("leaves a JPEG source unchanged", async () => {
    const file = new File(["jpeg"], "photo.jpg", { type: "image/jpeg" });
    await expect(normalizeAvatarFile(file)).resolves.toBe(file);
  });

  it("leaves a PNG source unchanged", async () => {
    const file = new File(["png"], "photo.png", { type: "image/png" });
    await expect(normalizeAvatarFile(file)).resolves.toBe(file);
  });

  it("leaves a WebP source unchanged", async () => {
    const file = new File(["webp"], "photo.webp", { type: "image/webp" });
    await expect(normalizeAvatarFile(file)).resolves.toBe(file);
  });

  it("leaves a non-image file unchanged (client never rejects — the server is the authority)", async () => {
    const file = new File(["not an image"], "notes.txt", { type: "text/plain" });
    await expect(normalizeAvatarFile(file)).resolves.toBe(file);
  });

  it("recognises HEIC by filename when iOS omits the MIME type", async () => {
    const file = new File(["heic"], "IMG_1234.HEIC", { type: "" });
    await expect(normalizeAvatarFile(file)).rejects.toMatchObject({
      name: "AvatarProcessingError",
      category: "read",
    });
  });

  it("reports an unreadable HEIF source when the browser cannot decode it", async () => {
    const file = new File(["heif"], "photo.heif", { type: "image/heif" });
    await expect(normalizeAvatarFile(file)).rejects.toMatchObject({
      name: "AvatarProcessingError",
      category: "read",
    });
  });

  it("reports a processing failure when decoding throws", async () => {
    vi.stubGlobal(
      "createImageBitmap",
      vi.fn().mockRejectedValue(new Error("source could not be decoded")),
    );
    const file = new File(["heic"], "IMG_9999.HEIC", { type: "image/heic" });
    await expect(normalizeAvatarFile(file)).rejects.toBeInstanceOf(AvatarProcessingError);
  });

  function stubDecodableCanvas() {
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
    return close;
  }

  it("converts a decodable HEIC source (by MIME type) to a metadata-free JPEG", async () => {
    const close = stubDecodableCanvas();
    const result = await normalizeAvatarFile(
      new File(["heic"], "IMG_1234.HEIC", { type: "image/heic" }),
    );
    expect(result.name).toBe("IMG_1234.jpg");
    expect(result.type).toBe("image/jpeg");
    expect(close).toHaveBeenCalledOnce();
  });

  it("converts a decodable HEIF source (by MIME type) to a metadata-free JPEG", async () => {
    stubDecodableCanvas();
    const result = await normalizeAvatarFile(
      new File(["heif"], "photo.heif", { type: "image/heif" }),
    );
    expect(result.name).toBe("photo.jpg");
    expect(result.type).toBe("image/jpeg");
  });

  it("converts a decodable HEIC source detected only by filename (empty MIME type)", async () => {
    stubDecodableCanvas();
    const result = await normalizeAvatarFile(new File(["heic"], "IMG_5555.heic", { type: "" }));
    expect(result.type).toBe("image/jpeg");
  });

  it("this is the conversion-BEFORE-validation guarantee the caller relies on: the returned File is always JPEG/HEIC-free before it ever reaches api.uploadAvatar()", async () => {
    stubDecodableCanvas();
    const result = await normalizeAvatarFile(
      new File(["heic"], "photo.HEIC", { type: "image/heic" }),
    );
    expect(result.type).not.toMatch(/heic|heif/i);
    expect(["image/jpeg", "image/png", "image/webp"]).toContain(result.type);
  });
});

describe("isImageFormatRejection", () => {
  it("recognises the backend's unsupported-format message", () => {
    expect(
      isImageFormatRejection({
        status: 422,
        message: "That image format is not supported. Please upload a JPEG, PNG or WebP photo.",
      }),
    ).toBe(true);
  });

  it("recognises the backend's undecodable-file message", () => {
    expect(
      isImageFormatRejection({
        status: 422,
        message: "That file could not be read as an image. Please upload a JPEG, PNG or WebP photo.",
      }),
    ).toBe(true);
  });

  it("recognises the backend's HEIC-unsupported-on-this-server message", () => {
    expect(
      isImageFormatRejection({
        status: 422,
        message: "HEIC/HEIF photos are not supported on this server. Please use JPEG, PNG or WebP.",
      }),
    ).toBe(true);
  });

  it("does not misclassify the unrelated 'no file was uploaded' 422", () => {
    expect(isImageFormatRejection({ status: 422, message: "No file was uploaded." })).toBe(false);
  });

  it("does not misclassify a 413 (too large) even if the wording were to overlap", () => {
    expect(
      isImageFormatRejection({
        status: 413,
        message: "That photo is too large. Please choose one under 5 MB.",
      }),
    ).toBe(false);
  });

  it("does not misclassify an unrelated network/upload failure", () => {
    expect(
      isImageFormatRejection({ status: 500, message: "Something went wrong. Please try again." }),
    ).toBe(false);
  });
});
