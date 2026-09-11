import { afterEach, describe, expect, it, vi } from "vitest";
import { CameraErrorCode } from "@capacitor/camera";
import {
  NativeAvatarPickerError,
  pickAvatarFromCamera,
  pickAvatarFromGallery,
  resetCameraProvider,
  resetFilesystemProvider,
  setCameraProviderForTesting,
  setFilesystemProviderForTesting,
  type CameraProvider,
  type FilesystemProvider,
} from "./native-avatar-picker";

// Coverage for the native iOS avatar selection path (Capacitor Camera +
// Filesystem plugins) introduced to replace the unreliable hidden HTML
// Photos-library <input type="file"> — see ADR 0013. Both the Camera plugin
// and the Filesystem plugin only behave like their real native selves
// inside a native shell, so every test substitutes its own providers (same
// seam as native-biometric.ts's setBiometricProviderForTesting) rather than
// mocking @capacitor/camera or @capacitor/filesystem module internals.
//
// REGRESSION COVERAGE: an earlier version read upload bytes via
// fetch(result.webPath), which failed on physical TestFlight builds for
// both Take Photo and Choose from Photos (MyKhaya's shell loads a remote
// server.url — see ADR 0012 — and webPath is documented by @capacitor/camera
// only as a display/preview convenience, not a fetch-for-bytes contract).
// The fix reads MediaResult.uri via Filesystem.readFile instead. The tests
// below assert fetch is never called for upload bytes on the native path,
// and that the Filesystem read is what actually produces the File.

function nativeError(code: string): Error & { code: string } {
  const error = new Error(`native failure ${code}`) as Error & { code: string };
  error.code = code;
  return error;
}

// A real, small JPEG-shaped byte sequence base64-encoded — Filesystem's own
// documented native return shape ("On native, the data is returned as a
// string" — see ReadFileResult). Content doesn't need to be a real JPEG for
// these tests: nothing here decodes image bytes, only converts them.
const SAMPLE_BASE64 = btoa("not a real jpeg but that's fine, nothing here decodes pixels");

function cameraProvider(overrides: Partial<CameraProvider> = {}): CameraProvider {
  return {
    takePhoto: async () => ({
      type: 0,
      saved: false,
      uri: "file:///var/mobile/Containers/Data/Application/XXXX/tmp/camera-photo.jpg",
      webPath: "capacitor://localhost/_capacitor_file_/camera-photo.jpg",
      metadata: { format: "jpeg", size: 1024 },
    }),
    chooseFromGallery: async () => ({
      results: [
        {
          type: 0,
          saved: false,
          uri: "file:///var/mobile/Containers/Data/Application/XXXX/tmp/gallery-photo.jpg",
          webPath: "capacitor://localhost/_capacitor_file_/gallery-photo.jpg",
          metadata: { format: "jpeg", size: 2048 },
        },
      ],
    }),
    ...overrides,
  };
}

function filesystemProvider(overrides: Partial<FilesystemProvider> = {}): FilesystemProvider {
  return {
    readFile: async () => ({ data: SAMPLE_BASE64 }),
    ...overrides,
  };
}

let originalFetch: typeof fetch;

afterEach(() => {
  resetCameraProvider();
  resetFilesystemProvider();
  if (originalFetch) global.fetch = originalFetch;
});

describe("pickAvatarFromCamera — native Take Photo", () => {
  it("uses the Capacitor Camera plugin's takePhoto, not chooseFromGallery", async () => {
    const base = cameraProvider();
    const takePhoto = vi.fn(() => base.takePhoto());
    const chooseFromGallery = vi.fn(() => base.chooseFromGallery());
    setCameraProviderForTesting({ takePhoto, chooseFromGallery });
    setFilesystemProviderForTesting(filesystemProvider());

    await pickAvatarFromCamera();

    expect(takePhoto).toHaveBeenCalledTimes(1);
    expect(chooseFromGallery).not.toHaveBeenCalled();
  });

  it("reads the returned uri via Filesystem, never fetch(webPath), and produces a real File", async () => {
    originalFetch = global.fetch;
    global.fetch = vi.fn() as unknown as typeof fetch;
    setCameraProviderForTesting(cameraProvider());
    const readFile = vi.fn(async () => ({ data: SAMPLE_BASE64 }));
    setFilesystemProviderForTesting({ readFile });

    const file = await pickAvatarFromCamera();

    expect(readFile).toHaveBeenCalledWith("file:///var/mobile/Containers/Data/Application/XXXX/tmp/camera-photo.jpg");
    expect(global.fetch).not.toHaveBeenCalled();
    expect(file).toBeInstanceOf(File);
    expect(file!.type).toBe("image/jpeg");
    expect(file!.size).toBeGreaterThan(0);
  });

  it("cancellation (OS-PLUG-CAMR-0006) returns null with no thrown error", async () => {
    setCameraProviderForTesting(
      cameraProvider({
        takePhoto: async () => {
          throw nativeError(CameraErrorCode.TakePhotoCancelled);
        },
      }),
    );

    await expect(pickAvatarFromCamera()).resolves.toBeNull();
  });

  it("permission denial (OS-PLUG-CAMR-0003) throws the MyKhaya camera-permission message", async () => {
    setCameraProviderForTesting(
      cameraProvider({
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

  it("an unexpected native picker failure maps to the read-failure message, never the raw native error", async () => {
    setCameraProviderForTesting(
      cameraProvider({
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
    const base = cameraProvider();
    const takePhoto = vi.fn(() => base.takePhoto());
    const chooseFromGallery = vi.fn(() => base.chooseFromGallery());
    setCameraProviderForTesting({ takePhoto, chooseFromGallery });
    setFilesystemProviderForTesting(filesystemProvider());

    await pickAvatarFromGallery();

    expect(chooseFromGallery).toHaveBeenCalledTimes(1);
    expect(takePhoto).not.toHaveBeenCalled();
  });

  it("reads the selected asset's uri via Filesystem, never fetch(webPath)", async () => {
    originalFetch = global.fetch;
    global.fetch = vi.fn() as unknown as typeof fetch;
    setCameraProviderForTesting(cameraProvider());
    const readFile = vi.fn(async () => ({ data: SAMPLE_BASE64 }));
    setFilesystemProviderForTesting({ readFile });

    const file = await pickAvatarFromGallery();

    expect(readFile).toHaveBeenCalledWith(
      "file:///var/mobile/Containers/Data/Application/XXXX/tmp/gallery-photo.jpg",
    );
    expect(global.fetch).not.toHaveBeenCalled();
    expect(file!.size).toBeGreaterThan(0);
  });

  it("a Filesystem/native file read failure gives the read-failure category, not a picker failure", async () => {
    setCameraProviderForTesting(cameraProvider());
    setFilesystemProviderForTesting({
      readFile: async () => {
        throw new Error("simulated native read failure");
      },
    });

    await expect(pickAvatarFromGallery()).rejects.toMatchObject({ category: "read" });
  });

  // Physical-device regression: a real trace showed the picker succeeding
  // (native-picker-returned outcome=success) and then Filesystem.readFile
  // rejecting with reason=plugin-rejected and no further detail — not
  // diagnosable from that alone. These tests prove the richer diagnostic
  // the fix adds, and that it never leaks the URI/path itself.
  describe("Filesystem read failure — safe diagnostics", () => {
    it("logs the error name, code, message and constructor, but never the raw error object or URI", async () => {
      const debugSpy = vi.spyOn(console, "debug").mockImplementation(() => {});
      setCameraProviderForTesting(cameraProvider());
      const rejection = Object.assign(new Error("File does not exist"), { code: "OS-PLUG-FLST-0002" });
      setFilesystemProviderForTesting({
        readFile: async () => {
          throw rejection;
        },
      });

      await expect(pickAvatarFromGallery()).rejects.toBeInstanceOf(NativeAvatarPickerError);

      const failedCall = debugSpy.mock.calls.find(([, details]) => {
        const record = details as Record<string, unknown> | undefined;
        return record?.reason === "plugin-rejected";
      });
      expect(failedCall).toBeDefined();
      const details = failedCall![1] as Record<string, unknown>;
      expect(details).toMatchObject({
        stage: "filesystem-read",
        reason: "plugin-rejected",
        errorName: "Error",
        errorMessage: "File does not exist",
        errorCode: "OS-PLUG-FLST-0002",
        errorConstructor: "Error",
      });

      debugSpy.mockRestore();
    });

    it("still classifies as read-failure and logs safely when the rejection is a plain non-Error value with no code", async () => {
      const debugSpy = vi.spyOn(console, "debug").mockImplementation(() => {});
      setCameraProviderForTesting(cameraProvider());
      setFilesystemProviderForTesting({
        // Some native bridges reject with a plain string/object rather than
        // an Error — deliberately simulated here to prove the diagnostic's
        // `cause instanceof Error ? ... : "UnknownError"` fallback actually
        // works, not just its Error-typed happy path.
        // eslint-disable-next-line @typescript-eslint/prefer-promise-reject-errors -- intentional non-Error rejection under test
        readFile: () => Promise.reject("native bridge failure"),
      });

      await expect(pickAvatarFromGallery()).rejects.toMatchObject({ category: "read" });

      const failedCall = debugSpy.mock.calls.find(([, details]) => {
        const record = details as Record<string, unknown> | undefined;
        return record?.reason === "plugin-rejected";
      });
      expect(failedCall).toBeDefined();
      const details = failedCall![1] as Record<string, unknown>;
      expect(details).toMatchObject({
        errorName: "UnknownError",
        errorMessage: "native bridge failure",
        errorCode: undefined,
        errorConstructor: "string",
      });

      debugSpy.mockRestore();
    });

    it("never logs the raw result.uri (path) anywhere, even on a read failure", async () => {
      const debugSpy = vi.spyOn(console, "debug").mockImplementation(() => {});
      const sensitiveUri =
        "file:///var/mobile/Containers/Data/Application/SECRET-DEVICE-UUID/tmp/photo-1234.jpg";
      setCameraProviderForTesting(
        cameraProvider({
          chooseFromGallery: async () => ({
            results: [{ type: 0, saved: false, uri: sensitiveUri, metadata: { format: "heic", size: 1_392_265 } }],
          }),
        }),
      );
      setFilesystemProviderForTesting({
        readFile: async () => {
          throw new Error("plugin rejected");
        },
      });

      await expect(pickAvatarFromGallery()).rejects.toBeInstanceOf(NativeAvatarPickerError);

      const allLoggedText = JSON.stringify(debugSpy.mock.calls);
      expect(allLoggedText).not.toContain(sensitiveUri);
      expect(allLoggedText).not.toContain("SECRET-DEVICE-UUID");

      debugSpy.mockRestore();
    });

    it("records uriScheme as 'file' for a file:// URI before attempting the read", async () => {
      const debugSpy = vi.spyOn(console, "debug").mockImplementation(() => {});
      setCameraProviderForTesting(
        cameraProvider({
          chooseFromGallery: async () => ({
            results: [{ type: 0, saved: false, uri: "file:///var/mobile/tmp/photo.heic" }],
          }),
        }),
      );
      setFilesystemProviderForTesting(filesystemProvider());

      await pickAvatarFromGallery();

      const startedCall = debugSpy.mock.calls.find(([stage]) => stage === "[avatar-upload] native-uri-read-started");
      expect(startedCall?.[1]).toMatchObject({ uriScheme: "file" });

      debugSpy.mockRestore();
    });

    it("records uriScheme as 'unknown' for a ph:// (Photos-provider) URI, without leaking the identifier", async () => {
      const debugSpy = vi.spyOn(console, "debug").mockImplementation(() => {});
      const phUri = "ph://1F3A2B9C-DEAD-BEEF-0000-ABCDEF123456/L0/001";
      setCameraProviderForTesting(
        cameraProvider({
          chooseFromGallery: async () => ({
            results: [{ type: 0, saved: false, uri: phUri, metadata: { format: "heic", size: 1_392_265 } }],
          }),
        }),
      );
      setFilesystemProviderForTesting({
        readFile: async () => {
          throw new Error("plugin rejected");
        },
      });

      await expect(pickAvatarFromGallery()).rejects.toBeInstanceOf(NativeAvatarPickerError);

      const startedCall = debugSpy.mock.calls.find(([stage]) => stage === "[avatar-upload] native-uri-read-started");
      expect(startedCall?.[1]).toMatchObject({ uriScheme: "ph" });
      const allLoggedText = JSON.stringify(debugSpy.mock.calls);
      expect(allLoggedText).not.toContain(phUri);
      expect(allLoggedText).not.toContain("1F3A2B9C-DEAD-BEEF-0000-ABCDEF123456");

      debugSpy.mockRestore();
    });

    it("records uriScheme as 'unknown' for an unrecognised scheme, still without leaking the path", async () => {
      const debugSpy = vi.spyOn(console, "debug").mockImplementation(() => {});
      setCameraProviderForTesting(
        cameraProvider({
          chooseFromGallery: async () => ({
            results: [{ type: 0, saved: false, uri: "content://media/external/images/media/9999" }],
          }),
        }),
      );
      setFilesystemProviderForTesting(filesystemProvider());

      await pickAvatarFromGallery();

      const startedCall = debugSpy.mock.calls.find(([stage]) => stage === "[avatar-upload] native-uri-read-started");
      expect(startedCall?.[1]).toMatchObject({ uriScheme: "unknown" });

      debugSpy.mockRestore();
    });

    it("the user-facing error message is unchanged by the richer diagnostics", async () => {
      setCameraProviderForTesting(cameraProvider());
      setFilesystemProviderForTesting({
        readFile: async () => {
          throw Object.assign(new Error("some native detail"), { code: "OS-PLUG-FLST-0002" });
        },
      });

      await expect(pickAvatarFromGallery()).rejects.toMatchObject({
        message: "We couldn’t read that photo. Please try another image.",
      });
    });
  });

  it("a missing uri in the picker result gives the read-failure category without calling Filesystem", async () => {
    setCameraProviderForTesting(
      cameraProvider({
        chooseFromGallery: async () => ({
          results: [{ type: 0, saved: false, webPath: "capacitor://localhost/_capacitor_file_/no-uri.jpg" }],
        }),
      }),
    );
    const readFile = vi.fn(async () => ({ data: SAMPLE_BASE64 }));
    setFilesystemProviderForTesting({ readFile });

    await expect(pickAvatarFromGallery()).rejects.toMatchObject({ category: "read" });
    expect(readFile).not.toHaveBeenCalled();
  });

  it("empty data from Filesystem gives the read-failure category", async () => {
    setCameraProviderForTesting(cameraProvider());
    setFilesystemProviderForTesting({ readFile: async () => ({ data: "" }) });

    await expect(pickAvatarFromGallery()).rejects.toMatchObject({ category: "read" });
  });

  it("cancellation (OS-PLUG-CAMR-0020) returns null with no thrown error", async () => {
    setCameraProviderForTesting(
      cameraProvider({
        chooseFromGallery: async () => {
          throw nativeError(CameraErrorCode.ChooseMediaCancelled);
        },
      }),
    );

    await expect(pickAvatarFromGallery()).resolves.toBeNull();
  });

  it("an empty result array (no thrown cancel code) is treated as a cancellation, not a failure", async () => {
    setCameraProviderForTesting(cameraProvider({ chooseFromGallery: async () => ({ results: [] }) }));

    await expect(pickAvatarFromGallery()).resolves.toBeNull();
  });

  it("permission denial (OS-PLUG-CAMR-0005) throws the MyKhaya photos-permission message", async () => {
    setCameraProviderForTesting(
      cameraProvider({
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
    // 9 MB of decoded source bytes, base64-encoded — comfortably under the
    // documented 20 MiB avatar upload ceiling, and large enough to exercise
    // the same base64 decode loop a real high-resolution iPhone photo
    // would go through. Built in chunks since String.fromCharCode(...arr)
    // itself blows the call-stack argument limit for an array this size.
    const decodedLength = 9_000_000;
    const bytes = new Uint8Array(decodedLength);
    let binary = "";
    const chunkSize = 32_768;
    for (let i = 0; i < bytes.length; i += chunkSize) {
      binary += String.fromCharCode(...bytes.subarray(i, i + chunkSize));
    }
    const largeBase64 = btoa(binary);

    setCameraProviderForTesting(cameraProvider());
    setFilesystemProviderForTesting({ readFile: async () => ({ data: largeBase64 }) });

    const file = await pickAvatarFromGallery();

    expect(file!.size).toBe(decodedLength);
  });

  it("HEIC/HEIF metadata produces an image/heic File, still via the same Filesystem read — no client-side HEIC decoding", async () => {
    setCameraProviderForTesting(
      cameraProvider({
        chooseFromGallery: async () => ({
          results: [
            {
              type: 0,
              saved: false,
              uri: "file:///var/mobile/tmp/original.heic",
              metadata: { format: "heic", size: 3_000_000 },
            },
          ],
        }),
      }),
    );
    setFilesystemProviderForTesting(filesystemProvider());

    const file = await pickAvatarFromGallery();

    expect(file!.type).toBe("image/heic");
    expect(file!.name).toMatch(/\.heic$/);
  });

  it("missing metadata still produces a valid File (defaults to JPEG), never rejected client-side", async () => {
    setCameraProviderForTesting(
      cameraProvider({
        chooseFromGallery: async () => ({
          results: [{ type: 0, saved: false, uri: "file:///var/mobile/tmp/unknown-format" }],
        }),
      }),
    );
    setFilesystemProviderForTesting(filesystemProvider());

    const file = await pickAvatarFromGallery();

    expect(file).toBeInstanceOf(File);
    expect(file!.type).toBe("image/jpeg");
  });
});
