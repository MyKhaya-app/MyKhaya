// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";

const publicConfig = vi.fn<() => Promise<{ maintenance_mode: boolean }>>();
vi.mock("@mykhaya/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@mykhaya/api-client")>();
  return { ...actual, api: { publicConfig: () => publicConfig() } };
});

const { ApiError } = await import("@mykhaya/api-client");
const { isMaintenanceError, MaintenanceScreen, MAINTENANCE_POLL_MS } = await import("./maintenance");

beforeEach(() => {
  publicConfig.mockReset();
});
afterEach(() => {
  vi.useRealTimers();
});

describe("isMaintenanceError", () => {
  it("recognises only the API's structured 503 maintenance_mode error", () => {
    expect(isMaintenanceError(new ApiError(503, "Maintenance", "maintenance_mode"))).toBe(true);
    // A generic 503 (e.g. a dependency outage) is not maintenance mode.
    expect(isMaintenanceError(new ApiError(503, "Unavailable"))).toBe(false);
    expect(isMaintenanceError(new ApiError(401, "Maintenance", "maintenance_mode"))).toBe(false);
    expect(isMaintenanceError(new Error("network"))).toBe(false);
    expect(isMaintenanceError(null)).toBe(false);
  });
});

describe("MaintenanceScreen", () => {
  it("shows the maintenance message while maintenance is still on", async () => {
    publicConfig.mockResolvedValue({ maintenance_mode: true });
    const onRecovered = vi.fn();
    render(<MaintenanceScreen onRecovered={onRecovered} />);

    expect(screen.getByRole("heading", { name: "MyKhaya is undergoing maintenance" })).toBeInTheDocument();
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Check again" }));
    });
    expect(onRecovered).not.toHaveBeenCalled();
  });

  it("recovers on its own once maintenance mode is switched off", async () => {
    vi.useFakeTimers();
    publicConfig.mockResolvedValue({ maintenance_mode: false });
    const onRecovered = vi.fn();
    render(<MaintenanceScreen onRecovered={onRecovered} />);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(MAINTENANCE_POLL_MS + 10);
    });
    expect(onRecovered).toHaveBeenCalledTimes(1);
  });

  it("stays on the screen if the status check itself fails", async () => {
    publicConfig.mockRejectedValue(new Error("offline"));
    const onRecovered = vi.fn();
    render(<MaintenanceScreen onRecovered={onRecovered} />);
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Check again" }));
    });
    expect(onRecovered).not.toHaveBeenCalled();
    expect(screen.getByTestId("maintenance-screen")).toBeInTheDocument();
  });
});
