// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderHook } from "@testing-library/react";

let nativeShell = false;
vi.mock("./native-runtime", () => ({
  isNativeShell: () => nativeShell,
}));

type BackButtonListener = (event: { canGoBack: boolean }) => void;
let backButtonListener: BackButtonListener | undefined;
const removeMock = vi.fn();
const addListenerMock = vi.fn((event: string, listener: BackButtonListener) => {
  if (event === "backButton") backButtonListener = listener;
  return Promise.resolve({ remove: removeMock });
});
const minimizeAppMock = vi.fn<() => Promise<void>>().mockResolvedValue(undefined);
vi.mock("@capacitor/app", () => ({
  App: {
    addListener: addListenerMock,
    minimizeApp: () => minimizeAppMock(),
  },
}));

const dismissTopmostMock = vi.fn<() => boolean>();
vi.mock("./dismissal-stack", () => ({
  dismissTopmost: () => dismissTopmostMock(),
}));

// Deliberately mocked, not exercised via a real pushState/popstate here —
// native-history-depth.test.ts covers that logic in isolation. This lets
// these tests assert the *decision order* (keyboard, then sheet, then
// history, then minimize) without depending on real browser history state.
const canNavigateBackMock = vi.fn<() => boolean>();
vi.mock("./native-history-depth", () => ({
  canNavigateBack: () => canNavigateBackMock(),
}));

const historyBackSpy = vi.spyOn(window.history, "back").mockImplementation(() => undefined);

async function fireBackButton() {
  // App.addListener resolves asynchronously; flush microtasks so the
  // listener is captured before firing it. The real Capacitor event still
  // carries `canGoBack`, but the handler no longer reads it — see
  // native-history-depth.ts's doc comment for why that field is the wrong
  // signal for this SPA — so this fires it with an arbitrary, unused value.
  await Promise.resolve();
  await Promise.resolve();
  backButtonListener?.({ canGoBack: false });
}

beforeEach(() => {
  nativeShell = true;
  backButtonListener = undefined;
  addListenerMock.mockClear();
  removeMock.mockClear();
  minimizeAppMock.mockClear();
  dismissTopmostMock.mockReset().mockReturnValue(false);
  canNavigateBackMock.mockReset().mockReturnValue(false);
  historyBackSpy.mockClear();
  document.body.innerHTML = "";
  (document.activeElement as HTMLElement | null)?.blur?.();
});

afterEach(() => {
  vi.resetModules();
});

describe("useNativeBackButton — platform gating", () => {
  it("registers no listener outside the native shell", async () => {
    nativeShell = false;
    const { useNativeBackButton } = await import("./native-back-button");
    renderHook(() => useNativeBackButton());

    await Promise.resolve();
    expect(addListenerMock).not.toHaveBeenCalled();
  });

  it("registers a backButton listener inside the native shell", async () => {
    const { useNativeBackButton } = await import("./native-back-button");
    renderHook(() => useNativeBackButton());

    await Promise.resolve();
    expect(addListenerMock).toHaveBeenCalledWith("backButton", expect.any(Function));
  });

  it("removes the native listener on unmount", async () => {
    const { useNativeBackButton } = await import("./native-back-button");
    const { unmount } = renderHook(() => useNativeBackButton());

    await Promise.resolve();
    unmount();
    await Promise.resolve();

    expect(removeMock).toHaveBeenCalledTimes(1);
  });
});

describe("useNativeBackButton — decision order", () => {
  it("blurs a focused input first and does nothing else (keyboard case)", async () => {
    const input = document.createElement("input");
    document.body.appendChild(input);
    input.focus();
    expect(document.activeElement).toBe(input);
    const blurSpy = vi.spyOn(input, "blur");

    const { useNativeBackButton } = await import("./native-back-button");
    renderHook(() => useNativeBackButton());
    await fireBackButton();

    expect(blurSpy).toHaveBeenCalledTimes(1);
    expect(dismissTopmostMock).not.toHaveBeenCalled();
    expect(historyBackSpy).not.toHaveBeenCalled();
    expect(minimizeAppMock).not.toHaveBeenCalled();
  });

  it("blurs a focused textarea the same way", async () => {
    const textarea = document.createElement("textarea");
    document.body.appendChild(textarea);
    textarea.focus();
    const blurSpy = vi.spyOn(textarea, "blur");

    const { useNativeBackButton } = await import("./native-back-button");
    renderHook(() => useNativeBackButton());
    await fireBackButton();

    expect(blurSpy).toHaveBeenCalledTimes(1);
    expect(historyBackSpy).not.toHaveBeenCalled();
  });

  it("treats a contentEditable element the same as an input for keyboard dismissal", async () => {
    const editable = document.createElement("div");
    // Set via the attribute, not the `.contentEditable` IDL property — this
    // jsdom version doesn't implement `isContentEditable` and doesn't
    // reflect the property setter to the attribute either, so this is the
    // only reliable way to exercise the attribute-based fallback check in
    // isEditableElement() (real WebKit/Blink support both).
    editable.setAttribute("contenteditable", "true");
    editable.tabIndex = 0;
    document.body.appendChild(editable);
    editable.focus();
    expect(document.activeElement).toBe(editable);
    const blurSpy = vi.spyOn(editable, "blur");

    const { useNativeBackButton } = await import("./native-back-button");
    renderHook(() => useNativeBackButton());
    await fireBackButton();

    expect(blurSpy).toHaveBeenCalledTimes(1);
    expect(dismissTopmostMock).not.toHaveBeenCalled();
  });

  it("closes the topmost open sheet/modal when nothing is focused (sheet/modal case)", async () => {
    dismissTopmostMock.mockReturnValue(true);
    canNavigateBackMock.mockReturnValue(true);

    const { useNativeBackButton } = await import("./native-back-button");
    renderHook(() => useNativeBackButton());
    await fireBackButton();

    expect(dismissTopmostMock).toHaveBeenCalledTimes(1);
    expect(historyBackSpy).not.toHaveBeenCalled();
    expect(minimizeAppMock).not.toHaveBeenCalled();
  });

  it("navigates back via browser history on a secondary route with no sheet open", async () => {
    dismissTopmostMock.mockReturnValue(false);
    canNavigateBackMock.mockReturnValue(true);

    const { useNativeBackButton } = await import("./native-back-button");
    renderHook(() => useNativeBackButton());
    await fireBackButton();

    expect(historyBackSpy).toHaveBeenCalledTimes(1);
    expect(minimizeAppMock).not.toHaveBeenCalled();
  });

  it("minimizes the app at the true root (no internal route to go back to) instead of exiting", async () => {
    dismissTopmostMock.mockReturnValue(false);
    canNavigateBackMock.mockReturnValue(false);

    const { useNativeBackButton } = await import("./native-back-button");
    renderHook(() => useNativeBackButton());
    await fireBackButton();

    expect(minimizeAppMock).toHaveBeenCalledTimes(1);
    expect(historyBackSpy).not.toHaveBeenCalled();
  });

  it("never reaches history/minimize when a sheet is open, even at history root", async () => {
    dismissTopmostMock.mockReturnValue(true);
    canNavigateBackMock.mockReturnValue(false);

    const { useNativeBackButton } = await import("./native-back-button");
    renderHook(() => useNativeBackButton());
    await fireBackButton();

    expect(dismissTopmostMock).toHaveBeenCalledTimes(1);
    expect(historyBackSpy).not.toHaveBeenCalled();
    expect(minimizeAppMock).not.toHaveBeenCalled();
  });
});
