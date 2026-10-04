import { afterEach, describe, expect, it, vi } from "vitest";
import { __resetDismissalStackForTesting, dismissTopmost, registerDismissible } from "./dismissal-stack";

afterEach(() => {
  __resetDismissalStackForTesting();
});

describe("dismissal-stack", () => {
  it("returns false when nothing is registered", () => {
    expect(dismissTopmost()).toBe(false);
  });

  it("calls the dismiss function and reports it was handled", () => {
    const dismiss = vi.fn();
    registerDismissible(dismiss);

    expect(dismissTopmost()).toBe(true);
    expect(dismiss).toHaveBeenCalledTimes(1);
  });

  it("closes the most-recently-registered entry first (LIFO)", () => {
    const outer = vi.fn();
    const inner = vi.fn();
    registerDismissible(outer);
    registerDismissible(inner);

    expect(dismissTopmost()).toBe(true);
    expect(inner).toHaveBeenCalledTimes(1);
    expect(outer).not.toHaveBeenCalled();
  });

  it("the unregister function removes only its own entry", () => {
    const outer = vi.fn();
    const inner = vi.fn();
    registerDismissible(outer);
    const unregisterInner = registerDismissible(inner);

    unregisterInner();

    expect(dismissTopmost()).toBe(true);
    expect(outer).toHaveBeenCalledTimes(1);
    expect(inner).not.toHaveBeenCalled();
  });

  it("does nothing if called twice (idempotent unregister)", () => {
    const dismiss = vi.fn();
    const unregister = registerDismissible(dismiss);

    unregister();
    unregister();

    expect(dismissTopmost()).toBe(false);
  });

  it("dismissing repeatedly walks the stack from the top down (as real unmount-on-dismiss does)", () => {
    // dismissTopmost() itself never removes an entry — a real BottomSheet's
    // onDismiss triggers a state update that unmounts it, and *that*
    // unregisters it (see bottom-sheet.tsx). Simulate that collapse here so
    // this test reflects real call sites rather than dismissTopmost's
    // internals.
    const a = vi.fn();
    const b = vi.fn();
    const c = vi.fn();
    const unregisterA = registerDismissible(a);
    const unregisterB = registerDismissible(b);
    const unregisterC = registerDismissible(c);
    a.mockImplementation(unregisterA);
    b.mockImplementation(unregisterB);
    c.mockImplementation(unregisterC);

    expect(dismissTopmost()).toBe(true);
    expect(dismissTopmost()).toBe(true);
    expect(dismissTopmost()).toBe(true);
    expect(dismissTopmost()).toBe(false);
    expect([a, b, c].every((fn) => fn.mock.calls.length === 1)).toBe(true);
  });
});
