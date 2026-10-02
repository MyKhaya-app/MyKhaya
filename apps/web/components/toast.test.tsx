import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Toast } from "./toast";

describe("Toast", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("renders a live overlay and dismisses after the default timeout", () => {
    const onDismiss = vi.fn();
    render(<Toast message="Routine updated." onDismiss={onDismiss} />);

    expect(screen.getByRole("status")).toHaveTextContent("Routine updated.");
    expect(screen.getByRole("status").closest(".consumer-toast-region")).toBeInTheDocument();

    act(() => vi.advanceTimersByTime(2499));
    expect(onDismiss).not.toHaveBeenCalled();
    act(() => vi.advanceTimersByTime(1));
    expect(onDismiss).toHaveBeenCalledTimes(1);
  });
});
