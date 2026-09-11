import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@capacitor/core", () => ({
  Capacitor: {
    isNativePlatform: vi.fn().mockReturnValue(false),
    getPlatform: vi.fn().mockReturnValue("web"),
  },
}));

import {
  classifyAvatarBackendFailure,
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

  it("preserves a raw HEIC source for server-side processing", async () => {
    const file = new File(["heic"], "IMG_1234.HEIC", { type: "" });
    await expect(normalizeAvatarFile(file)).resolves.toBe(file);
  });

  it("preserves a raw HEIF source for server-side processing", async () => {
    const file = new File(["heif"], "photo.heif", { type: "image/heif" });
    await expect(normalizeAvatarFile(file)).resolves.toBe(file);
  });

  it("rejects an empty selected file before creating multipart data", async () => {
    await expect(normalizeAvatarFile(new File([], "empty.jpg", { type: "image/jpeg" }))).rejects.toMatchObject({
      category: "read",
    });
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

  it("classifies the backend's undecodable-file message as a read failure", () => {
    expect(
      classifyAvatarBackendFailure({
        status: 422,
        message: "That file could not be read as an image. Please upload a JPEG, PNG or WebP photo.",
      }),
    ).toBe("read");
  });

  it("classifies the backend's HEIC-unsupported message as unsupported", () => {
    expect(
      classifyAvatarBackendFailure({
        status: 422,
        message: "HEIC/HEIF photos are not supported on this server. Please use JPEG, PNG or WebP.",
      }),
    ).toBe("unsupported");
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
