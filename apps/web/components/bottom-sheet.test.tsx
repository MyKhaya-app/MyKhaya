// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render } from "@testing-library/react";
import { BottomSheet } from "./bottom-sheet";

let nativeShell = false;
vi.mock("./native-runtime", () => ({
  isNativeShell: () => nativeShell,
}));

beforeEach(() => {
  nativeShell = false;
  document.body.className = "";
  document.body.removeAttribute("style");
});

afterEach(() => {
  document.body.className = "";
  document.body.removeAttribute("style");
  document.querySelector(".app-content-scroll-region")?.remove();
});

describe("BottomSheet — scroll lock, browser/PWA", () => {
  it("locks document.body (position: fixed) rather than any content region", () => {
    const { unmount } = render(<BottomSheet title="Sheet" onDismiss={vi.fn()} children="x" />);

    expect(document.body.classList.contains("sheet-open")).toBe(true);
    expect(document.body.style.position).toBe("fixed");

    unmount();

    expect(document.body.classList.contains("sheet-open")).toBe(false);
    expect(document.body.style.position).toBe("");
  });
});

describe("BottomSheet — scroll lock, native shell", () => {
  it("locks the .app-content-scroll-region instead of document.body", () => {
    nativeShell = true;
    const region = document.createElement("div");
    region.className = "app-content-scroll-region";
    document.body.appendChild(region);

    const { unmount } = render(<BottomSheet title="Sheet" onDismiss={vi.fn()} children="x" />);

    // body/html never scroll in the native shell (see styles.css), so the
    // browser-only position:fixed body-lock trick must not apply here.
    expect(document.body.style.position).toBe("");
    expect(region.style.overflow).toBe("hidden");

    unmount();

    expect(region.style.overflow).toBe("");
  });

  it("falls back to the browser lock if the scroll region isn't mounted", () => {
    nativeShell = true;
    // No .app-content-scroll-region in the DOM (e.g. a transient auth
    // loading/offline screen that renders no AppShell content) — never
    // crash, just fall back to locking body.
    const { unmount } = render(<BottomSheet title="Sheet" onDismiss={vi.fn()} children="x" />);

    expect(document.body.style.position).toBe("fixed");

    unmount();
  });
});

// Regression coverage for the calendar-save "zoom" bug: closing a sheet
// (e.g. Save from an event editor) while a text field still has focus must
// deterministically blur that field before its DOM is torn down, and must
// never scroll the page when focus is restored afterwards — see
// bottom-sheet.tsx's cleanup comment for the full mechanism.
describe("BottomSheet — focus handling on close (calendar-save zoom/jump regression)", () => {
  it("blurs a focused field inside the sheet before unmounting, rather than letting the browser discover it vanished", () => {
    const trigger = document.createElement("button");
    document.body.appendChild(trigger);
    trigger.focus();

    const { unmount, getByLabelText } = render(
      <BottomSheet title="Add event" onDismiss={vi.fn()}>
        <input aria-label="Title" />
      </BottomSheet>,
    );

    const input = getByLabelText("Title");
    input.focus();
    expect(document.activeElement).toBe(input);

    const blurSpy = vi.spyOn(input, "blur");
    unmount();

    expect(blurSpy).toHaveBeenCalled();
    trigger.remove();
  });

  it("restores focus to the pre-open trigger using preventScroll, never causing a scroll-into-view jump", () => {
    const trigger = document.createElement("button");
    document.body.appendChild(trigger);
    trigger.focus();

    const { unmount } = render(<BottomSheet title="Sheet" onDismiss={vi.fn()} children="x" />);

    const focusSpy = vi.spyOn(trigger, "focus");
    unmount();

    expect(focusSpy).toHaveBeenCalledWith({ preventScroll: true });
    trigger.remove();
  });

  it("does not attempt to blur anything when nothing inside the sheet is focused", () => {
    const trigger = document.createElement("button");
    document.body.appendChild(trigger);
    trigger.focus();

    // Nothing under the dialog is ever explicitly focused here — must not
    // throw or blur an unrelated element.
    const { unmount } = render(<BottomSheet title="Sheet" onDismiss={vi.fn()} children="x" />);
    expect(() => unmount()).not.toThrow();
    trigger.remove();
  });
});
