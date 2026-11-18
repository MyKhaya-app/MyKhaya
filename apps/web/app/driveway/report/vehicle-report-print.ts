// Browser (non-native) printing of the generated Vehicle Report PDF.
//
// The tab is opened synchronously inside the click handler, before the PDF is
// requested, so popup blockers see the user's gesture rather than a window
// opened after an async API call. It is opened *without* `noopener`, because
// with `noopener` window.open() always returns null and a successful open
// can't be told apart from a blocked one. `opener` is cleared straight away
// instead, which gives the same protection: the new tab can't reach back into
// MyKhaya. The tab only ever shows our own same-origin blob: PDF.

/** How often an open print tab is checked for having been closed. */
export const PRINT_TAB_POLL_MS = 2_000;
/** The PDF's object URL is released after this even if the tab stays open;
    the browser's PDF viewer has loaded the document long before then. */
export const PRINT_URL_MAX_LIFETIME_MS = 10 * 60 * 1_000;

/** Opens the placeholder tab. Returns null when the browser blocked it. */
export function openPrintWindow(): Window | null {
  const printWindow = window.open("", "_blank");
  if (!printWindow) return null;
  try {
    printWindow.opener = null;
  } catch {
    // Some browsers make `opener` read-only on a fresh window; nothing to undo.
  }
  try {
    printWindow.document.title = "Preparing your Vehicle Report…";
    printWindow.document.body.textContent = "Preparing your Vehicle Report PDF…";
  } catch {
    // Cosmetic only.
  }
  return printWindow;
}

/**
 * Shows `pdf` in a tab returned by openPrintWindow(). Returns false, without
 * creating an object URL, if the user has already closed that tab.
 *
 * The object URL is revoked when the tab is closed, or after
 * PRINT_URL_MAX_LIFETIME_MS, whichever comes first, never immediately (the
 * tab loads the URL asynchronously after navigation starts).
 */
export function showPdfInPrintWindow(printWindow: Window, pdf: Blob): boolean {
  if (printWindow.closed) return false;
  const url = URL.createObjectURL(pdf);
  let released = false;
  const release = () => {
    if (released) return;
    released = true;
    window.clearInterval(poll);
    window.clearTimeout(expiry);
    URL.revokeObjectURL(url);
  };
  const poll = window.setInterval(() => {
    if (printWindow.closed) release();
  }, PRINT_TAB_POLL_MS);
  const expiry = window.setTimeout(release, PRINT_URL_MAX_LIFETIME_MS);
  try {
    printWindow.location.href = url;
  } catch {
    release();
    return false;
  }
  return true;
}
