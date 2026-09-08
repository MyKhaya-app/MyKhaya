const HEIF_MIME_TYPES = new Set(["image/heic", "image/heif"]);

function isHeifFile(file: File): boolean {
  const type = file.type.trim().toLowerCase();
  const name = file.name.trim().toLowerCase();
  return HEIF_MIME_TYPES.has(type) || /\.(heic|heif)$/.test(name);
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
  if (!isHeifFile(file)) return file;

  let bitmap: CanvasImageSource | undefined;
  let closableBitmap: ImageBitmap | undefined;
  let objectUrl: string | undefined;
  try {
    if (typeof createImageBitmap === "function") {
      closableBitmap = await createImageBitmap(file, { imageOrientation: "from-image" });
      bitmap = closableBitmap;
    } else {
      objectUrl = URL.createObjectURL(file);
      const image = new Image();
      image.src = objectUrl;
      await image.decode();
      bitmap = image;
    }

    const sourceWidth = "width" in bitmap ? bitmap.width : 0;
    const sourceHeight = "height" in bitmap ? bitmap.height : 0;
    if (!sourceWidth || !sourceHeight) return file;
    const maxDimension = 2048;
    const scale = Math.min(1, maxDimension / Math.max(sourceWidth, sourceHeight));
    const canvas = document.createElement("canvas");
    canvas.width = Math.max(1, Math.round(sourceWidth * scale));
    canvas.height = Math.max(1, Math.round(sourceHeight * scale));
    const context = canvas.getContext("2d");
    if (!context) return file;
    context.drawImage(bitmap, 0, 0, canvas.width, canvas.height);

    const blob = await new Promise<Blob | null>((resolve) =>
      canvas.toBlob(resolve, "image/jpeg", 0.9),
    );
    if (!blob) return file;
    return new File([blob], file.name.replace(/\.(heic|heif)$/i, ".jpg"), {
      type: "image/jpeg",
      lastModified: file.lastModified,
    });
  } catch {
    return file;
  } finally {
    closableBitmap?.close();
    if (objectUrl) URL.revokeObjectURL(objectUrl);
  }
}
