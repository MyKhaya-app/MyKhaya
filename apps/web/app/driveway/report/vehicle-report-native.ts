import { Directory, Filesystem } from "@capacitor/filesystem";

const CLEANUP_DELAY_MS = 5 * 60 * 1000;

export interface NativeReportFile {
  path: string;
  uri: string;
}

export class NativeVehicleReportError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "NativeVehicleReportError";
  }
}

function nativeReportPath(filename: string): string {
  return `vehicle-reports/${filename}`;
}

export async function writeNativeVehicleReport(
  filename: string,
  base64: string,
): Promise<NativeReportFile> {
  const path = nativeReportPath(filename);
  try {
    await Filesystem.writeFile({
      path,
      data: base64,
      directory: Directory.Cache,
      recursive: true,
    });
    const { uri } = await Filesystem.getUri({ path, directory: Directory.Cache });
    return { path, uri };
  } catch {
    throw new NativeVehicleReportError("The PDF could not be saved in the app.");
  }
}

export function scheduleNativeVehicleReportCleanup(file: NativeReportFile): void {
  window.setTimeout(() => {
    void Filesystem.deleteFile({ path: file.path, directory: Directory.Cache }).catch(() => undefined);
  }, CLEANUP_DELAY_MS);
}

export async function presentNativeVehicleReport(
  blob: Blob,
  filename: string,
  base64: string,
  title: string,
): Promise<void> {
  const file = await writeNativeVehicleReport(filename, base64);
  const nativeFile = new File([blob], filename, { type: "application/pdf" });
  const canShareFiles =
    typeof navigator !== "undefined" &&
    typeof navigator.share === "function" &&
    (!navigator.canShare || navigator.canShare({ files: [nativeFile] }));
  if (!canShareFiles) {
    scheduleNativeVehicleReportCleanup(file);
    throw new NativeVehicleReportError(
      "Native PDF saving is unavailable in this app build. Please update the app and try again.",
    );
  }
  try {
    await navigator.share({ title, files: [nativeFile] });
  } finally {
    // Cache files remain available long enough for the receiving document
    // provider to finish reading them; the OS may reclaim Cache earlier.
    scheduleNativeVehicleReportCleanup(file);
  }
}
