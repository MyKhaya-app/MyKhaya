// @vitest-environment jsdom
import { fireEvent, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useActivityHeartbeat } from "./use-activity-heartbeat";

const { heartbeat } = vi.hoisted(() => ({ heartbeat: vi.fn().mockResolvedValue(undefined) }));
vi.mock("@mykhaya/api-client", () => ({ api: { activityHeartbeat: heartbeat } }));
vi.mock("./native-runtime", () => ({ isNativeShell: () => false }));
vi.mock("@capacitor/app", () => ({ App: { addListener: vi.fn() } }));

function Harness({ enabled = true }: { enabled?: boolean }) {
  useActivityHeartbeat(enabled);
  return null;
}

describe("useActivityHeartbeat", () => {
  afterEach(() => {
    vi.clearAllMocks();
    Object.defineProperty(document, "visibilityState", { configurable: true, value: "visible" });
  });

  it("signals authenticated visible foreground and resumes after hiding", async () => {
    vi.useFakeTimers();
    render(<Harness />);
    expect(heartbeat).toHaveBeenCalledTimes(1);
    await Promise.resolve();
    await Promise.resolve();
    Object.defineProperty(document, "visibilityState", { configurable: true, value: "hidden" });
    fireEvent(document, new Event("visibilitychange"));
    vi.advanceTimersByTime(5 * 60 * 1000);
    expect(heartbeat).toHaveBeenCalledTimes(1);
    Object.defineProperty(document, "visibilityState", { configurable: true, value: "visible" });
    fireEvent(document, new Event("visibilitychange"));
    expect(heartbeat).toHaveBeenCalledTimes(2);
    vi.useRealTimers();
  });

  it("does not signal while disabled, including after lifecycle events", () => {
    render(<Harness enabled={false} />);
    fireEvent(document, new Event("visibilitychange"));
    expect(heartbeat).not.toHaveBeenCalled();
  });
});
