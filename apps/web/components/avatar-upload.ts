import { nativePlatform } from "./native-runtime";

const HEIF_MIME_TYPES = new Set(["image/heic", "image/heif"]);

export type AvatarFailureCategory = "unsupported" | "read" | "processing";

export class AvatarProcessingError extends Error {
  constructor(
    public readonly category: AvatarFailureCategory,
    message: string,
    options?: { cause?: unknown },
  ) {
    super(message, options);
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
  return error.status === 422 && /JPEG, PNG or WebP/i.test(error.message);
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
    name,
    extension: name.match(/\.([^.]+)$/)?.[1]?.toLowerCase() || "(none)",
    type: file.type || "(empty)",
    size: file.size,
    hasObjectUrlSupport:
      typeof URL !== "undefined" && typeof URL.createObjectURL === "function",
  };
}

/**
 * HEIF is a normal source format on iOS, but it is not a useful long-term
 * browser upload format. When the current WebKit/browser can decode it, draw
 * it to a fresh JPEG so EXIF/GPS metadata cannot travel with the upload. Some
 * WKWebView versions cannot decode HEIF from JavaScript; in that case the
 * original bytes are deliberately returned and the API's pillow-heif path
 * remains the authoritative fallback.
 */
export async function normalizeAvatarFile(file: File): Promise<File> {
  const heif = isHeifFile(file);
  logAvatarDiagnostic("picker-returned", {
    selectedAssetAvailable: true,
    sourceType: "browser-file",
    uriScheme: "(not exposed by HTML file input)",
    ...sourceMetadata(file),
    heifDetected: heif,
  });
  if (!heif) return file;

  let bitmap: CanvasImageSource | undefined;
  let closableBitmap: ImageBitmap | undefined;
  let objectUrl: string | undefined;
  try {
    logAvatarDiagnostic("image-decode-started", { sourceType: file.type || "(empty)" });
    if (typeof createImageBitmap === "function") {
      closableBitmap = await createImageBitmap(file, { imageOrientation: "from-image" });
      bitmap = closableBitmap;
    } else {
      if (typeof URL === "undefined" || typeof URL.createObjectURL !== "function") {
        throw new AvatarProcessingError("read", "The selected image has no readable browser URL.");
      }
      objectUrl = URL.createObjectURL(file);
      const image = new Image();
      image.src = objectUrl;
      await image.decode();
      bitmap = image;
    }
    logAvatarDiagnostic("image-decode-completed", { sourceType: file.type || "(empty)" });

    const sourceWidth = "width" in bitmap ? bitmap.width : 0;
    const sourceHeight = "height" in bitmap ? bitmap.height : 0;
    if (!sourceWidth || !sourceHeight) {
      throw new AvatarProcessingError("read", "The selected image has no readable dimensions.");
    }
    const maxDimension = 2048;
    const scale = Math.min(1, maxDimension / Math.max(sourceWidth, sourceHeight));
    const canvas = document.createElement("canvas");
    canvas.width = Math.max(1, Math.round(sourceWidth * scale));
    canvas.height = Math.max(1, Math.round(sourceHeight * scale));
    logAvatarDiagnostic("resize-started", { width: canvas.width, height: canvas.height });
    const context = canvas.getContext("2d");
    if (!context) {
      throw new AvatarProcessingError("processing", "The image canvas could not be created.");
    }
    context.drawImage(bitmap, 0, 0, canvas.width, canvas.height);

    const blob = await new Promise<Blob | null>((resolve) =>
      canvas.toBlob(resolve, "image/jpeg", 0.9),
    );
    if (!blob) throw new AvatarProcessingError("processing", "The image could not be converted.");
    logAvatarDiagnostic("resize-completed", { outputSize: blob.size });
    const converted = new File([blob], file.name.replace(/\.(heic|heif)$/i, ".jpg"), {
      type: "image/jpeg",
      lastModified: file.lastModified,
    });
    logAvatarDiagnostic("file-created", {
      outputType: converted.type,
      outputSize: converted.size,
    });
    return converted;
  } catch (cause) {
    logAvatarDiagnostic("conversion-failed", {
      errorName: cause instanceof Error ? cause.name : "UnknownError",
      error: cause instanceof Error ? cause.message : String(cause),
    });
    if (cause instanceof AvatarProcessingError) throw cause;
    throw new AvatarProcessingError("processing", "The selected image could not be prepared.", { cause });
  } finally {
    closableBitmap?.close();
    if (objectUrl) URL.revokeObjectURL(objectUrl);
  }
}
