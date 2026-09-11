import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CameraErrorCode } from "@capacitor/camera";
import {
  NativeAvatarPickerError,
  pickAvatarFromCamera,
  pickAvatarFromGallery,
  resetCameraProvider,
  setCameraProviderForTesting,
  type CameraProvider,
} from "./native-avatar-picker";

// Coverage for the native iOS avatar selection path (Capacitor Camera
// plugin) introduced to replace the unreliable hidden HTML Photos-library
// <input type="file"> — see ADR 0013. The real Camera plugin only behaves
// like an iOS camera inside a native shell, so every test substitutes its
// own CameraProvider (same seam as native-biometric.ts's
// setBiometricProviderForTesting) rather than mocking @capacitor/camera's
// module internals.

function nativeError(code: string): Error & { code: string } {
  const error = new Error(`native failure ${code}`) as Error & { code: string };
  error.code = code;
  return error;
}

function jpegBlob(bytes = 1024): Blob {
  return new Blob([new Uint8Array(bytes)], { type: "image/jpeg" });
}

// Only the two Response members mediaResultToFile actually reads (`ok`,
// `blob()`) — avoids relying on the real Response/Blob constructors to
// round-trip a body + content-type faithfully, which jsdom does not do
// reliably for this.
function fetchOk(blob: Blob): typeof fetch {
  return vi.fn(async () => ({ ok: true, blob: async () => blob }) as unknown as Response) as unknown as typeof fetch;
}

function provider(overrides: Partial<CameraProvider> = {}): CameraProvider {
  return {
    takePhoto: async () => ({
      type: 0,
      saved: false,
      webPath: "capacitor://localhost/_capacitor_file_/camera-photo.jpg",
      metadata: { format: "jpeg", size: 1024 },
    }),
    chooseFromGallery: async () => ({
      results: [
        {
          type: 0,
          saved: false,
          webPath: "capacitor://localhost/_capacitor_file_/gallery-photo.jpg",
          metadata: { format: "jpeg", size: 2048 },
        },
      ],
    }),
    ...overrides,
  };
}

let originalFetch: typeof fetch;

beforeEach(() => {
  originalFetch = global.fetch;
  global.fetch = fetchOk(jpegBlob());
});

afterEach(() => {
  resetCameraProvider();
  global.fetch = originalFetch;
});

describe("pickAvatarFromCamera — native Take Photo", () => {
  it("uses the Capacitor Camera plugin's takePhoto, not chooseFromGallery", async () => {
    const base = provider();
    const takePhoto = vi.fn(() => base.takePhoto());
    const chooseFromGallery = vi.fn(() => base.chooseFromGallery());
    setCameraProviderForTesting({ takePhoto, chooseFromGallery });

    await pickAvatarFromCamera();

    expect(takePhoto).toHaveBeenCalledTimes(1);
    expect(chooseFromGallery).not.toHaveBeenCalled();
  });

  it("converts the returned webPath into a real File suitable for api.uploadAvatar()", async () => {
    setCameraProviderForTesting(provider());

    const file = await pickAvatarFromCamera();

    expect(file).toBeInstanceOf(File);
    expect(file!.type).toBe("image/jpeg");
    expect(file!.size).toBeGreaterThan(0);
    expect(global.fetch).toHaveBeenCalledWith("capacitor://localhost/_capacitor_file_/camera-photo.jpg");
  });

  it("cancellation (OS-PLUG-CAMR-0006) returns null with no thrown error", async () => {
    setCameraProviderForTesting(
      provider({
        takePhoto: async () => {
          throw nativeError(CameraErrorCode.TakePhotoCancelled);
        },
      }),
    );

    await expect(pickAvatarFromCamera()).resolves.toBeNull();
  });

  it("permission denial (OS-PLUG-CAMR-0003) throws the MyKhaya camera-permission message", async () => {
    setCameraProviderForTesting(
      provider({
        takePhoto: async () => {
          throw nativeError(CameraErrorCode.CameraPermissionDenied);
        },
      }),
    );

    await expect(pickAvatarFromCamera()).rejects.toMatchObject({
      category: "permission",
      message: "MyKhaya doesn’t have permission to access your camera. You can allow access in iPhone Settings.",
    });
  });

  it("an unexpected native failure maps to the read-failure message, never the raw native error", async () => {
    setCameraProviderForTesting(
      provider({
        takePhoto: async () => {
          throw nativeError(CameraErrorCode.TakePhotoFailed);
        },
      }),
    );

    let caught: unknown;
    try {
      await pickAvatarFromCamera();
    } catch (error) {
      caught = error;
    }
    expect(caught).toBeInstanceOf(NativeAvatarPickerError);
    expect((caught as NativeAvatarPickerError).message).toBe(
      "We couldn’t read that photo. Please try another image.",
    );
    expect((caught as NativeAvatarPickerError).message).not.toMatch(/OS-PLUG-CAMR|native failure/);
  });
});

describe("pickAvatarFromGallery — native Choose from Photos", () => {
  it("uses the Capacitor Camera plugin's chooseFromGallery, not takePhoto", async () => {
    const base = provider();
    const takePhoto = vi.fn(() => base.takePhoto());
    const chooseFromGallery = vi.fn(() => base.chooseFromGallery());
    setCameraProviderForTesting({ takePhoto, chooseFromGallery });

    await pickAvatarFromGallery();

    expect(chooseFromGallery).toHaveBeenCalledTimes(1);
    expect(takePhoto).not.toHaveBeenCalled();
  });

  it("converts the selected asset's webPath into a real File", async () => {
    setCameraProviderForTesting(provider());

    const file = await pickAvatarFromGallery();

    expect(file).toBeInstanceOf(File);
    expect(file!.size).toBeGreaterThan(0);
    expect(global.fetch).toHaveBeenCalledWith("capacitor://localhost/_capacitor_file_/gallery-photo.jpg");
  });

  it("a HEIC gallery asset the plugin re-encoded to JPEG reaches the caller as image/jpeg, no client-side HEIC decoding", async () => {
    setCameraProviderForTesting(
      provider({
        chooseFromGallery: async () => ({
          results: [
            {
              type: 0,
              saved: false,
              webPath: "capacitor://localhost/_capacitor_file_/heic-source.jpg",
              // The plugin's own native re-encode already happened — format
              // reflects the JPEG it wrote out, not the original HEIC asset.
              metadata: { format: "jpg", size: 3_000_000 },
            },
          ],
        }),
      }),
    );

    const file = await pickAvatarFromGallery();

    expect(file!.type).toBe("image/jpeg");
    expect(file!.name).toMatch(/\.jpg$/);
  });

  it("cancellation (OS-PLUG-CAMR-0020) returns null with no thrown error", async () => {
    setCameraProviderForTesting(
      provider({
        chooseFromGallery: async () => {
          throw nativeError(CameraErrorCode.ChooseMediaCancelled);
        },
      }),
    );

    await expect(pickAvatarFromGallery()).resolves.toBeNull();
  });

  it("an empty result array (no thrown cancel code) is treated as a cancellation, not a failure", async () => {
    setCameraProviderForTesting(provider({ chooseFromGallery: async () => ({ results: [] }) }));

    await expect(pickAvatarFromGallery()).resolves.toBeNull();
  });

  it("permission denial (OS-PLUG-CAMR-0005) throws the MyKhaya photos-permission message", async () => {
    setCameraProviderForTesting(
      provider({
        chooseFromGallery: async () => {
          throw nativeError(CameraErrorCode.GalleryPermissionDenied);
        },
      }),
    );

    await expect(pickAvatarFromGallery()).rejects.toMatchObject({
      category: "permission",
      message: "MyKhaya doesn’t have permission to access your photos. You can allow access in iPhone Settings.",
    });
  });

  it("a large legitimate phone photo is not rejected client-side", async () => {
    global.fetch = fetchOk(jpegBlob(9_000_000));
    setCameraProviderForTesting(provider());

    const file = await pickAvatarFromGallery();

    expect(file!.size).toBe(9_000_000);
  });

  it("a webPath that cannot be fetched maps to the read-failure category", async () => {
    global.fetch = vi.fn(async () => ({ ok: false }) as unknown as Response) as unknown as typeof fetch;
    setCameraProviderForTesting(provider());

    await expect(pickAvatarFromGallery()).rejects.toMatchObject({ category: "read" });
  });

  it("a missing webPath maps to the read-failure category without calling fetch", async () => {
    setCameraProviderForTesting(
      provider({
        chooseFromGallery: async () => ({ results: [{ type: 0, saved: false }] }),
      }),
    );

    await expect(pickAvatarFromGallery()).rejects.toMatchObject({ category: "read" });
    expect(global.fetch).not.toHaveBeenCalled();
  });
});
