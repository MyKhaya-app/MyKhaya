// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, within } from "@testing-library/react";
import { useState } from "react";
import { BottomSheet } from "./bottom-sheet";
import { dismissTopmost } from "./dismissal-stack";

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

  it("dismisses only from the backdrop, never from an interaction inside the panel", () => {
    const onDismiss = vi.fn();
    const { container } = render(
      <BottomSheet title="Sheet" onDismiss={onDismiss}>
        <button type="button">Inside</button>
      </BottomSheet>,
    );
    const backdrop = container.querySelector(".sheet-backdrop") as HTMLElement;
    const panel = container.querySelector(".bottom-sheet") as HTMLElement;
    const inside = within(panel).getByRole("button", { name: "Inside" });

    fireEvent.click(inside);
    expect(onDismiss).not.toHaveBeenCalled();
    fireEvent.click(panel);
    expect(onDismiss).not.toHaveBeenCalled();
    fireEvent.click(backdrop);
    expect(onDismiss).toHaveBeenCalledTimes(1);
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

  it("restores the native scroll region exactly across repeated open/close cycles", () => {
    nativeShell = true;
    const region = document.createElement("div");
    region.className = "app-content-scroll-region";
    region.style.overflow = "auto";
    document.body.appendChild(region);

    function ToggleSheet() {
      const [open, setOpen] = useState(true);
      return open ? (
        <BottomSheet title="Sheet" onDismiss={() => setOpen(false)} children="x" />
      ) : (
        <button type="button" onClick={() => setOpen(true)}>Reopen</button>
      );
    }

    const { getByRole, rerender } = render(<ToggleSheet />);
    expect(region.style.overflow).toBe("hidden");
    fireEvent.click(getByRole("button", { name: "Close dialog" }));
    expect(region.style.overflow).toBe("auto");

    fireEvent.click(getByRole("button", { name: "Reopen" }));
    expect(region.style.overflow).toBe("hidden");
    rerender(<ToggleSheet />);
    fireEvent.click(getByRole("button", { name: "Close dialog" }));
    expect(region.style.overflow).toBe("auto");
  });
});

// Regression coverage for the calendar-save "zoom" bug: closing a sheet
// (e.g. Save from an event editor) while a text field still has focus must
// deterministically blur that field before its DOM is torn down, and must
// never scroll the page when focus is restored afterwards — see
// bottom-sheet.tsx's cleanup comment for the full mechanism.
// Regression coverage for Android hardware/gesture Back: a mounted
// BottomSheet must be closeable by the shared back-button handler
// (native-back-button.ts) without either of them knowing about the other
// directly — see dismissal-stack.ts, the seam between them.
describe("BottomSheet — dismissal-stack registration (Android Back integration)", () => {
  it("registers itself as dismissible while mounted, and dismissTopmost() calls the latest onDismiss", () => {
    const onDismiss = vi.fn();
    const { unmount } = render(<BottomSheet title="Sheet" onDismiss={onDismiss} children="x" />);

    expect(dismissTopmost()).toBe(true);
    expect(onDismiss).toHaveBeenCalledTimes(1);

    unmount();
  });

  it("unregisters on unmount — dismissTopmost() finds nothing once closed", () => {
    const onDismiss = vi.fn();
    const { unmount } = render(<BottomSheet title="Sheet" onDismiss={onDismiss} children="x" />);

    unmount();

    expect(dismissTopmost()).toBe(false);
    expect(onDismiss).not.toHaveBeenCalled();
  });

  it("dismisses the topmost of two stacked sheets first, leaving the other registered", () => {
    const outer = vi.fn();
    const inner = vi.fn();
    const { unmount: unmountOuter } = render(<BottomSheet title="Outer" onDismiss={outer} children="x" />);
    const { unmount: unmountInner } = render(<BottomSheet title="Inner" onDismiss={inner} children="x" />);

    expect(dismissTopmost()).toBe(true);
    expect(inner).toHaveBeenCalledTimes(1);
    expect(outer).not.toHaveBeenCalled();

    unmountInner();
    expect(dismissTopmost()).toBe(true);
    expect(outer).toHaveBeenCalledTimes(1);

    unmountOuter();
  });

  it("always calls the latest onDismiss even after a parent re-render passes a new callback", () => {
    const first = vi.fn();
    const second = vi.fn();
    const { rerender, unmount } = render(<BottomSheet title="Sheet" onDismiss={first} children="x" />);

    rerender(<BottomSheet title="Sheet" onDismiss={second} children="x" />);
    expect(dismissTopmost()).toBe(true);
    expect(first).not.toHaveBeenCalled();
    expect(second).toHaveBeenCalledTimes(1);

    unmount();
  });
});

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
