import { Camera, CameraErrorCode, MediaTypeSelection, type MediaResult } from "@capacitor/camera";
import { logAvatarDiagnostic } from "./avatar-upload";

// Native iOS avatar selection — see ADR 0013's "Native/browser avatar
// selection boundary". The unreliable hidden HTML Photos-library
// <input type="file"> is never used inside the native shell; this module is
// the one place native picker/permission/asset-conversion handling lives.
// takePhoto/chooseFromGallery are the current (8.1.0+) Camera plugin API —
// the older getPhoto({source: CameraSource...}) it replaces is deprecated
// and slated for removal, so this deliberately targets the supported one
// rather than the API the deprecated symbols still technically work under.

export type NativeAvatarFailureCategory = "permission" | "read" | "unknown";

export class NativeAvatarPickerError extends Error {
  constructor(
    public readonly category: NativeAvatarFailureCategory,
    message: string,
  ) {
    super(message);
    this.name = "NativeAvatarPickerError";
  }
}

// Injectable seam — the real Camera plugin only behaves like an iOS camera
// inside a native shell; tests substitute their own provider rather than
// mocking @capacitor/camera's module internals. Mirrors the established
// pattern in native-biometric.ts (setBiometricProviderForTesting).
export interface CameraProvider {
  takePhoto(): Promise<MediaResult>;
  chooseFromGallery(): Promise<{ results: MediaResult[] }>;
}

const defaultProvider: CameraProvider = {
  // quality 90 matches the HTML-input path's historical implicit behaviour
  // (no client-side recompression at all — this is the plugin's own JPEG
  // re-encode quality when it writes out webPath, still far above what
  // visibly loses fidelity, and the backend recompresses to WebP anyway).
  // includeMetadata: true is the only way to get MediaMetadata.format/size,
  // used to build a sensible filename/MIME without decoding image bytes
  // ourselves. saveToGallery: false — MyKhaya has no reason to duplicate a
  // just-taken profile photo into the user's own Camera Roll.
  takePhoto: () => Camera.takePhoto({ quality: 90, includeMetadata: true, saveToGallery: false }),
  chooseFromGallery: () =>
    Camera.chooseFromGallery({
      mediaType: MediaTypeSelection.Photo,
      allowMultipleSelection: false,
      includeMetadata: true,
      quality: 90,
    }),
};

let provider: CameraProvider = defaultProvider;

export function setCameraProviderForTesting(next: CameraProvider): void {
  provider = next;
}

export function resetCameraProvider(): void {
  provider = defaultProvider;
}

function nativeErrorCode(error: unknown): string | undefined {
  return typeof error === "object" && error !== null && "code" in error
    ? String((error as { code: unknown }).code)
    : undefined;
}

// The plugin's own structured CameraErrorCode (see @capacitor/camera's
// README "Errors" table) — never a raw native message or filesystem path
// surfaced to the user. Cancellation and permission denial are the two
// codes users hit constantly and must read correctly; every other failure
// (bad data, gallery fetch failure, plugin/process errors) collapses to the
// same "couldn't read that photo" wording the four-category error taxonomy
// this feature exposes to the user already uses for an unreadable file —
// there is no fifth bucket to invent for "camera hardware unavailable" etc.
function categoriseNativeError(error: unknown): "cancelled" | NativeAvatarFailureCategory {
  const code = nativeErrorCode(error);
  if (code === CameraErrorCode.TakePhotoCancelled || code === CameraErrorCode.ChooseMediaCancelled) {
    return "cancelled";
  }
  if (code === CameraErrorCode.CameraPermissionDenied || code === CameraErrorCode.GalleryPermissionDenied) {
    return "permission";
  }
  return "read";
}

const READ_FAILURE_MESSAGE = "We couldn’t read that photo. Please try another image.";

function permissionMessage(source: "camera" | "photos"): string {
  return source === "camera"
    ? "MyKhaya doesn’t have permission to access your camera. You can allow access in iPhone Settings."
    : "MyKhaya doesn’t have permission to access your photos. You can allow access in iPhone Settings.";
}

// Converts the plugin's MediaResult into a browser File suitable for the
// existing api.uploadAvatar() multipart flow — without decoding image bytes
// in JavaScript. `webPath` is Capacitor's supported approach for this: a
// URL served through the native webview's own local scheme handler, safe to
// fetch() from inside WKWebView (a raw `uri`/`file://` path is not — see
// ADR 0013). `thumbnail` is deliberately never used here: it is a
// low-resolution base64 preview, not the original image.
async function mediaResultToFile(result: MediaResult, filenamePrefix: string): Promise<File> {
  if (!result.webPath) {
    throw new NativeAvatarPickerError("read", READ_FAILURE_MESSAGE);
  }
  logAvatarDiagnostic("native-asset-received", {
    sourceType: "capacitor-camera-plugin",
    hasWebPath: true,
    hasUri: Boolean(result.uri),
    resultFormat: result.metadata?.format ?? "(unknown)",
    byteSize: result.metadata?.size ?? "(unknown)",
  });
  let response: Response;
  try {
    response = await fetch(result.webPath);
  } catch {
    throw new NativeAvatarPickerError("read", READ_FAILURE_MESSAGE);
  }
  if (!response.ok) {
    throw new NativeAvatarPickerError("read", READ_FAILURE_MESSAGE);
  }
  const blob = await response.blob();
  if (!blob.size) {
    throw new NativeAvatarPickerError("read", READ_FAILURE_MESSAGE);
  }
  // Android/iOS may report "jpg" rather than "jpeg" for the same format
  // (documented on MediaMetadata.format) — normalise before comparing.
  const format = result.metadata?.format?.toLowerCase().replace(/^jpg$/, "jpeg");
  const extension = format === "png" ? "png" : format === "webp" ? "webp" : "jpg";
  const mimeType =
    blob.type || (format === "png" ? "image/png" : format === "webp" ? "image/webp" : "image/jpeg");
  const file = new File([blob], `${filenamePrefix}-${Date.now()}.${extension}`, { type: mimeType });
  logAvatarDiagnostic("native-blob-created", {
    sourceType: "capacitor-camera-plugin",
    name: file.name,
    type: file.type,
    size: file.size,
  });
  return file;
}

// Returns the selected/captured photo as a File, or null if the user
// cancelled (never an error — matches the HTML-input picker's own
// no-file-selected behaviour). Throws NativeAvatarPickerError for every
// other outcome (permission denial, unreadable asset).
async function pickAvatar(source: "camera" | "photos"): Promise<File | null> {
  logAvatarDiagnostic("native-picker-opened", { source });
  try {
    if (source === "camera") {
      const result = await provider.takePhoto();
      logAvatarDiagnostic("native-picker-returned", { source, outcome: "success" });
      return await mediaResultToFile(result, "camera");
    }
    const { results } = await provider.chooseFromGallery();
    logAvatarDiagnostic("native-picker-returned", {
      source,
      outcome: "success",
      resultCount: results.length,
    });
    const first = results[0];
    // Empty results with no thrown cancel code — treat the same as a
    // cancellation rather than a failure; the user simply chose nothing.
    if (!first) return null;
    return await mediaResultToFile(first, "photos");
  } catch (cause) {
    if (cause instanceof NativeAvatarPickerError) throw cause;
    const category = categoriseNativeError(cause);
    logAvatarDiagnostic("native-picker-returned", { source, outcome: category });
    if (category === "cancelled") return null;
    throw new NativeAvatarPickerError(
      category,
      category === "permission" ? permissionMessage(source) : READ_FAILURE_MESSAGE,
    );
  }
}

export function pickAvatarFromCamera(): Promise<File | null> {
  return pickAvatar("camera");
}

export function pickAvatarFromGallery(): Promise<File | null> {
  return pickAvatar("photos");
}
