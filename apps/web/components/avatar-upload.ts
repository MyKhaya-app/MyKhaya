import { nativePlatform } from "./native-runtime";

// Includes the ISO-BMFF "sequence" container variants (Live Photos, burst-
// style HEIC assets) pillow-heif's own get_file_mimetype() can report — see
// mykhaya.avatars.processing, which never gates on any of these strings
// (or the client's file.type at all): this set only feeds non-authoritative
// diagnostics (heifDetected below), never accept/reject decisions.
const HEIF_MIME_TYPES = new Set([
  "image/heic",
  "image/heif",
  "image/heic-sequence",
  "image/heif-sequence",
]);

export type AvatarFailureCategory = "unsupported" | "read" | "processing";

export class AvatarProcessingError extends Error {
  constructor(
    public readonly category: AvatarFailureCategory,
    message: string,
  ) {
    super(message);
    this.name = "AvatarProcessingError";
  }
}

function isHeifFile(file: File): boolean {
  const type = file.type.trim().toLowerCase();
  const name = file.name.trim().toLowerCase();
  return HEIF_MIME_TYPES.has(type) || /\.(heic|heif)$/.test(name);
}

/**
 * The backend's own decode-validation rejection (see
 * mykhaya.avatars.processing.UnsupportedImageError) is written for
 * troubleshooting, not for end users — it literally says "JPEG, PNG or
 * WebP", which is exactly what an ordinary iPhone photo owner should never
 * need to see or understand (they don't know, and shouldn't need to know,
 * what HEIC is). Matched by wording rather than status code alone because
 * 422 is also used for the unrelated "no file was uploaded" case.
 */
export function isImageFormatRejection(error: { status: number; message: string }): boolean {
  return classifyAvatarBackendFailure(error) === "unsupported";
}

export type AvatarBackendFailureCategory = "unsupported" | "read" | "unknown";

export function classifyAvatarBackendFailure(error: {
  status: number;
  message: string;
}): AvatarBackendFailureCategory | null {
  if (error.status !== 422) return null;
  if (/no file was uploaded/i.test(error.message)) return "unknown";
  if (/could not be read as an image/i.test(error.message)) return "read";
  if (/format is not supported|HEIC\/HEIF photos are not supported|JPEG, PNG or WebP/i.test(error.message)) {
    return "unsupported";
  }
  return "unknown";
}

// Deliberately not gated on NODE_ENV: the native iOS/TestFlight build is a
// production web export, so a NODE_ENV-only gate would hide device evidence.
// console.debug is inert for end users and only visible via Safari Web
// Inspector attached to the device. Never logs image bytes or EXIF/location
// metadata — only picker/format facts needed to diagnose this pipeline.
export function logAvatarDiagnostic(stage: string, details: Record<string, unknown>) {
  console.debug(`[avatar-upload] ${stage}`, { platform: nativePlatform(), ...details });
}

function sourceMetadata(file: File): Record<string, unknown> {
  const name = file.name.trim();
  return {
    constructor: file.constructor?.name || "unknown",
    isFile: typeof File !== "undefined" && file instanceof File,
    filename: name,
    extension: name.match(/\.([^.]+)$/)?.[1]?.toLowerCase() || "(none)",
    mimeType: file.type || "(empty)",
    fileType: file.type || "(empty)",
    size: file.size,
    lastModified: file.lastModified || undefined,
    heifDetected: isHeifFile(file),
  };
}

/**
 * The API is the single image-processing authority. It decodes by content,
 * accepts JPEG/PNG/WebP and HEIF when pillow-heif is available, strips EXIF,
 * normalises orientation, crops, resizes, and stores WebP. Keeping the source
 * File intact avoids fragile HEIF decoding differences between WebKit versions.
 */
export async function normalizeAvatarFile(file: File): Promise<File> {
  logAvatarDiagnostic("validation-started", {
    sourceType: "browser-file",
    uriScheme: "(not exposed by HTML file input)",
    ...sourceMetadata(file),
  });
  if (!file.size) {
    logAvatarDiagnostic("validation-failed", { category: "read", reason: "empty-file" });
    throw new AvatarProcessingError("read", "The selected photo is empty.");
  }
  logAvatarDiagnostic("validation-completed", {
    filename: file.name,
    mimeType: file.type || "(empty)",
    size: file.size,
    clientProcessing: "server-authoritative",
  });
  logAvatarDiagnostic("decode-deferred-to-backend", {
    reason: "avoid WKWebView-specific HEIC conversion",
    normalizedFilename: file.name,
    normalizedMimeType: file.type || "(empty)",
    normalizedSize: file.size,
  });
  return file;
}
