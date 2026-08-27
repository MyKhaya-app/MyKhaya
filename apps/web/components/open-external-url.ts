import { Browser } from "@capacitor/browser";
import { isNativeShell } from "./native-runtime";

// Task §13 (External URL handling): an external product/support/legal link
// must open in the system browser (or, in the shell, an in-app
// SFSafariViewController via @capacitor/browser), never take over the
// authenticated main WebView. In an ordinary browser tab, this is the
// existing `target="_blank"` behaviour and needs no change — this helper is
// for call sites that need to work correctly in *both* contexts.
export async function openExternalUrl(url: string): Promise<void> {
  if (isNativeShell()) {
    await Browser.open({ url });
    return;
  }
  window.open(url, "_blank", "noopener,noreferrer");
}
