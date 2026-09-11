import { Camera, CameraErrorCode, MediaTypeSelection, type MediaResult } from "@capacitor/camera";
import { Filesystem } from "@capacitor/filesystem";
import { logAvatarDiagnostic } from "./avatar-upload";

// Native iOS avatar selection — see ADR 0013's "Native/browser avatar
// selection boundary". The unreliable hidden HTML Photos-library
// <input type="file"> is never used inside the native shell; this module is
// the one place native picker/permission/asset-conversion handling lives.
// takePhoto/chooseFromGallery are the current (8.1.0+) Camera plugin API —
// the older getPhoto({source: CameraSource...}) it replaces is deprecated
// and slated for removal, so this deliberately targets the supported one
// rather than the API the deprecated symbols still technically work under.
//
// REGRESSION FIX: an earlier version of this module read upload bytes via
// `fetch(result.webPath)`. That broke both Take Photo and Choose from
// Photos on physical TestFlight builds ("We couldn't read that photo").
// Root cause: MediaResult.webPath is documented by @capacitor/camera only
// as "a path that can be used to set the src attribute of a media item for
// efficient loading and rendering" — a display/preview convenience, never
// a documented fetch-for-bytes contract — and MyKhaya's shell loads a
// REMOTE server.url (https://dev.mykhaya.app / https://mykhaya.app, see
// ADR 0012), not Capacitor's default bundled-app local origin, which is
// exactly the configuration Capacitor's own docs say to use `uri` (via the
// Filesystem plugin) for full-resolution native bytes instead of `webPath`.
// This module now reads `result.uri` through Filesystem.readFile — the
// officially documented mechanism — never `fetch(webPath)` for upload
// bytes. `webPath` is retained only for its documented purpose (nothing in
// this profile flow currently needs a preview, so it isn't used at all
// today, but a future preview should use it, never re-derive bytes from it).

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
  // re-encode quality when it writes out the asset, still far above what
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

// Injectable seam for the Filesystem read step, same rationale as
// CameraProvider above — real Filesystem.readFile only does anything
// meaningful on a native device.
export interface FilesystemProvider {
  readFile(path: string): Promise<{ data: string | Blob }>;
}

const defaultFilesystemProvider: FilesystemProvider = {
  readFile: (path) => Filesystem.readFile({ path }),
};

let filesystemProvider: FilesystemProvider = defaultFilesystemProvider;

export function setFilesystemProviderForTesting(next: FilesystemProvider): void {
  filesystemProvider = next;
}

export function resetFilesystemProvider(): void {
  filesystemProvider = defaultFilesystemProvider;
}

function nativeErrorCode(error: unknown): string | undefined {
  return typeof error === "object" && error !== null && "code" in error
    ? String((error as { code: unknown }).code)
    : undefined;
}

// "Error type/constructor" for diagnostics — e.g. distinguishing a plain
// rejected string/object (some native bridges reject with a plain object,
// not an Error) from a real Error subclass, without ever touching message
// content that might embed a path.
function errorConstructorName(error: unknown): string {
  if (typeof error === "object" && error !== null) {
    return error.constructor?.name ?? "Object";
  }
  return typeof error;
}

// Derived from the URI *scheme* only — e.g. "file" from
// "file:///var/...", "ph" from "ph://<asset-id>" (the modern Photos
// local-identifier scheme), "assets-library" from the legacy
// assets-library:// scheme. Never the rest of the URI: the path/identifier
// after the scheme can be sensitive (device filesystem layout, Photos
// asset identifiers) and diagnosing *this* failure only needs to know
// which kind of URI the Camera plugin handed back, not where it points —
// see the physical-device trace this diagnostic was added to explain
// (Filesystem.readFile rejecting a Photos-provider/security-scoped URI it
// cannot directly open is the leading theory, and the scheme is exactly
// what would confirm or rule that out).
function nativeUriScheme(uri: string): "file" | "ph" | "assets-library" | "unknown" {
  const match = /^([a-z][a-z0-9+.-]*):/i.exec(uri);
  const scheme = match?.[1]?.toLowerCase();
  if (scheme === "file") return "file";
  if (scheme === "ph") return "ph";
  if (scheme === "assets-library") return "assets-library";
  return "unknown";
}

// The plugin's own structured CameraErrorCode (see @capacitor/camera's
// README "Errors" table) — never a raw native message or filesystem path
// surfaced to the user. Cancellation and permission denial are the two
// codes users hit constantly and must read correctly; every other failure
// (bad data, gallery fetch failure, plugin/process errors) collapses to the
// same "couldn't read that photo" wording the four-category error taxonomy
// this feature exposes to the user already uses for an unreadable file —
// there is no fifth bucket to invent for "camera hardware unavailable" etc.
// This only ever classifies a *picker*-stage failure (the plugin call
// itself); a failure reading the returned asset afterwards is a distinct
// diagnostic stage — see nativeAssetToFile below — even though it surfaces
// the same user-facing "read" message.
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

// Filesystem.readFile without a `directory` returns the file's bytes as a
// base64 string on native (see @capacitor/filesystem's ReadFileResult:
// "Blob is only available on Web. On native, the data is returned as a
// string."). Decoding it via atob keeps the whole conversion local and
// synchronous — no further network-ish call of the kind that made webPath
// unreliable in the first place. A 20 MiB original (the documented avatar
// upload ceiling) becomes a ~27 MiB base64 string crossing the JS bridge —
// real, but a one-off, in-memory, synchronous operation on a modern
// device; not the sort of cost that justifies falling back to an
// undocumented, already-proven-unreliable transport. See ADR 0013.
function base64ToBlob(base64: string, mimeType: string): Blob {
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) {
    bytes[i] = binary.charCodeAt(i);
  }
  return new Blob([bytes], { type: mimeType });
}

// Android/iOS may return "jpg" rather than "jpeg" for the same format, and
// HEIC/HEIF gallery assets are reported as such when the plugin doesn't
// re-encode them (see MediaMetadata.format's own documentation) — normalise
// before comparing. Missing/unusual metadata never blocks an otherwise
// valid read: it only affects the filename/MIME guess, defaulting to JPEG,
// while the backend remains the sole authority on what the bytes actually
// are (see ADR 0013's "Shared binary upload processing").
function extensionAndMimeFromFormat(format: string | undefined): { extension: string; mimeType: string } {
  const normalised = format?.toLowerCase().replace(/^jpg$/, "jpeg");
  switch (normalised) {
    case "png":
      return { extension: "png", mimeType: "image/png" };
    case "webp":
      return { extension: "webp", mimeType: "image/webp" };
    case "heic":
    case "heif":
      return { extension: "heic", mimeType: "image/heic" };
    default:
      return { extension: "jpg", mimeType: "image/jpeg" };
  }
}

// Converts the plugin's MediaResult into a browser File suitable for the
// existing api.uploadAvatar() multipart flow — without decoding image bytes
// in JavaScript. Reads `uri` (the native file reference) via the Filesystem
// plugin; never `webPath` (see the module-level regression-fix comment).
async function nativeAssetToFile(result: MediaResult, filenamePrefix: string): Promise<File> {
  logAvatarDiagnostic("native-asset-received", {
    sourceType: "capacitor-camera-plugin",
    hasWebPath: Boolean(result.webPath),
    hasUri: Boolean(result.uri),
    resultFormat: result.metadata?.format ?? "(unknown)",
    metadataByteSize: result.metadata?.size ?? "(unknown)",
  });

  if (!result.uri) {
    logAvatarDiagnostic("native-uri-read-failed", { stage: "filesystem-read", reason: "no-uri-in-result" });
    throw new NativeAvatarPickerError("read", READ_FAILURE_MESSAGE);
  }

  logAvatarDiagnostic("native-uri-read-started", {
    stage: "filesystem-read",
    uriScheme: nativeUriScheme(result.uri),
  });
  let data: string | Blob;
  try {
    ({ data } = await filesystemProvider.readFile(result.uri));
  } catch (cause) {
    // Development-only diagnostic: enough to distinguish *why*
    // Filesystem.readFile rejected (permission, unsupported URI scheme,
    // missing file, plugin/bridge error, ...) without ever logging the
    // URI/path itself, image bytes, base64, tokens, or EXIF/GPS. The
    // user-facing message stays the same generic wording regardless of
    // what's logged here — this is for developers reading device console
    // output, never surfaced in the UI.
    logAvatarDiagnostic("native-uri-read-failed", {
      stage: "filesystem-read",
      reason: "plugin-rejected",
      errorName: cause instanceof Error ? cause.name : "UnknownError",
      errorMessage: cause instanceof Error ? cause.message : String(cause),
      errorCode: nativeErrorCode(cause),
      errorConstructor: errorConstructorName(cause),
    });
    throw new NativeAvatarPickerError("read", READ_FAILURE_MESSAGE);
  }

  const { extension, mimeType } = extensionAndMimeFromFormat(result.metadata?.format);
  const filename = `${filenamePrefix}-${Date.now()}.${extension}`;

  let blob: Blob;
  if (typeof data === "string") {
    if (!data) {
      logAvatarDiagnostic("native-uri-read-failed", { stage: "filesystem-read", reason: "empty-data" });
      throw new NativeAvatarPickerError("read", READ_FAILURE_MESSAGE);
    }
    logAvatarDiagnostic("native-uri-read-succeeded", {
      stage: "filesystem-read",
      resultFormat: "base64",
      base64Length: data.length,
    });
    try {
      blob = base64ToBlob(data, mimeType);
    } catch {
      logAvatarDiagnostic("native-blob-construction-failed", { stage: "blob-construction" });
      throw new NativeAvatarPickerError("read", READ_FAILURE_MESSAGE);
    }
  } else {
    // Filesystem's Web implementation returns a real Blob directly — not
    // reached on native (native-shell avatar selection is iOS-only, gated
    // by isNativeShell()), kept only so this compiles against the plugin's
    // shared cross-platform type rather than asserting the branch away.
    logAvatarDiagnostic("native-uri-read-succeeded", { stage: "filesystem-read", resultFormat: "blob" });
    blob = data;
  }

  if (!blob.size) {
    logAvatarDiagnostic("native-blob-construction-failed", { stage: "blob-construction", reason: "empty-blob" });
    throw new NativeAvatarPickerError("read", READ_FAILURE_MESSAGE);
  }

  const file = new File([blob], filename, { type: mimeType });
  logAvatarDiagnostic("native-blob-created", {
    sourceType: "capacitor-camera-plugin",
    stage: "blob-construction",
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
  logAvatarDiagnostic("native-picker-opened", { source, stage: "picker" });
  try {
    if (source === "camera") {
      const result = await provider.takePhoto();
      logAvatarDiagnostic("native-picker-returned", { source, stage: "picker", outcome: "success" });
      return await nativeAssetToFile(result, "camera");
    }
    const { results } = await provider.chooseFromGallery();
    logAvatarDiagnostic("native-picker-returned", {
      source,
      stage: "picker",
      outcome: "success",
      resultCount: results.length,
    });
    const first = results[0];
    // Empty results with no thrown cancel code — treat the same as a
    // cancellation rather than a failure; the user simply chose nothing.
    if (!first) return null;
    return await nativeAssetToFile(first, "photos");
  } catch (cause) {
    if (cause instanceof NativeAvatarPickerError) throw cause;
    const category = categoriseNativeError(cause);
    logAvatarDiagnostic("native-picker-returned", { source, stage: "picker", outcome: category });
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
