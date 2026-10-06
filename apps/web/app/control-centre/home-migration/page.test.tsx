import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import HomeMigrationPage from "./page";

const { get, post, upload } = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), upload: vi.fn() }));
vi.mock("@mykhaya/api-client", () => ({
  ApiError: class ApiError extends Error {},
  platformApi: { get, post, upload },
}));
vi.mock("@/components/platform-shell", () => ({ PlatformShell: ({ children }: { children: React.ReactNode }) => <>{children}</> }));

describe("Home Migration PCC page", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    get.mockResolvedValue({ enabled: false, enabled_at: null, environment: "development", packages: [] });
  });

  it("shows the safe disabled state and does not call migration operations", async () => {
    render(<HomeMigrationPage />);
    expect(await screen.findByText(/Home Migration is disabled/)).toBeTruthy();
    expect(post).not.toHaveBeenCalled();
    expect(upload).not.toHaveBeenCalled();
  });

  it("shows only the DEV export workflow when enabled", async () => {
    get.mockResolvedValue({ enabled: true, enabled_at: "2026-01-01T00:00:00Z", environment: "development", packages: [] });
    get.mockResolvedValueOnce({ enabled: true, enabled_at: "2026-01-01T00:00:00Z", environment: "development", packages: [] }).mockResolvedValueOnce([{ id: "home-1", name: "Test Home", member_count: 2 }]);
    render(<HomeMigrationPage />);
    await waitFor(() => expect(screen.getByText("Export a Home")).toBeTruthy());
    expect(screen.queryByText("Import a Home into PROD")).toBeNull();
  });
});
