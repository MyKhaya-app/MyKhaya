import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import userEvent from "@testing-library/user-event";
import HomeMigrationPage from "./page";

const { get, post, upload } = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  upload: vi.fn(),
}));
vi.mock("@mykhaya/api-client", () => ({
  ApiError: class ApiError extends Error {},
  platformApi: { get, post, upload },
}));
vi.mock("@/components/platform-shell", () => ({
  PlatformShell: ({ children }: { children: React.ReactNode }) => (
    <>{children}</>
  ),
}));

describe("Home Migration PCC page", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    get.mockResolvedValue({
      enabled: false,
      enabled_at: null,
      environment: "development",
      packages: [],
    });
  });

  it("shows the safe disabled state and does not call migration operations", async () => {
    render(<HomeMigrationPage />);
    expect(await screen.findByText(/Home Migration is disabled/)).toBeTruthy();
    expect(post).not.toHaveBeenCalled();
    expect(upload).not.toHaveBeenCalled();
  });

  it("shows only the DEV export workflow with clean member labels", async () => {
    get.mockResolvedValue({
      enabled: true,
      enabled_at: "2026-01-01T00:00:00Z",
      environment: "development",
      packages: [],
    });
    get
      .mockResolvedValueOnce({
        enabled: true,
        enabled_at: "2026-01-01T00:00:00Z",
        environment: "development",
        packages: [],
      })
      .mockResolvedValueOnce([
        { id: "home-1", name: "Hales Home", member_count: 4 },
        { id: "home-2", name: "Developer Home", member_count: 1 },
      ]);
    render(<HomeMigrationPage />);
    await waitFor(() => expect(screen.getByText("Export a Home")).toBeTruthy());
    expect(screen.queryByText("Import a Home into PROD")).toBeNull();
    expect(
      screen.getByRole("option", { name: "Hales Home \u00b7 4 members" }),
    ).toBeTruthy();
    expect(
      screen.getByRole("option", { name: "Developer Home \u00b7 1 member" }),
    ).toBeTruthy();
    expect(screen.queryByText(/[\u00c3\u00c2\u00e2\ufffd]/)).toBeNull();
  });

  it("requires explicit confirmation and sends the backend dry-run contract", async () => {
    const user = userEvent.setup();
    const pkg = {
      id: "package-1",
      migration_id: "migration-1",
      package_checksum: "checksum",
      summary: { member_count: 4, asset_count: 0 },
      status: "uploaded",
    };
    get.mockResolvedValue({
      enabled: true,
      enabled_at: null,
      environment: "production",
      packages: [],
    });
    upload.mockResolvedValue(pkg);
    post.mockResolvedValue({
      ...pkg,
      dry_run_report: {
        status: "READY_TO_IMPORT",
        matched_existing_users: 4,
        new_users: 0,
      },
    });
    const { container } = render(<HomeMigrationPage />);
    await screen.findByText("Import a Home into PROD");

    const file = new File(["{}"], "migration.json", {
      type: "application/json",
    });
    fireEvent.change(container.querySelector('input[type="file"]')!, {
      target: { files: [file] },
    });
    await user.click(
      screen.getByRole("button", { name: "Upload and validate" }),
    );
    await screen.findByText("Migration:");
    await user.click(screen.getByRole("button", { name: "Run dry-run" }));
    expect(post).not.toHaveBeenCalled();

    const dialog = screen.getByRole("dialog");
    await user.type(
      within(dialog).getByLabelText(/Reason for this administrative action/i),
      "Validate this migration package",
    );
    await user.click(
      within(dialog).getByRole("button", { name: "Run dry-run" }),
    );
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/home-migration/dry-run", {
        package_id: "package-1",
        reason: "Validate this migration package",
        confirmed: true,
      }),
    );
  });

  it("sends explicit confirmation when importing only after a ready dry-run", async () => {
    const user = userEvent.setup();
    const pkg = {
      id: "package-1",
      migration_id: "migration-1",
      package_checksum: "checksum",
      summary: { member_count: 4, asset_count: 0 },
      status: "ready",
      dry_run_report: {
        status: "READY_TO_IMPORT",
        matched_existing_users: 4,
        new_users: 0,
      },
    };
    get.mockResolvedValue({
      enabled: true,
      enabled_at: null,
      environment: "production",
      packages: [],
    });
    upload.mockResolvedValue(pkg);
    post.mockResolvedValue({ status: "completed" });
    const { container } = render(<HomeMigrationPage />);
    await screen.findByText("Import a Home into PROD");
    const file = new File(["{}"], "migration.json", {
      type: "application/json",
    });
    fireEvent.change(container.querySelector('input[type="file"]')!, {
      target: { files: [file] },
    });
    await user.click(
      screen.getByRole("button", { name: "Upload and validate" }),
    );
    await screen.findByText("migration-1");
    await user.type(
      screen.getByLabelText(/Type the migration ID/i),
      "migration-1",
    );
    await user.click(
      screen.getByRole("button", { name: "Import Home into PROD" }),
    );
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/home-migration/import", {
        package_id: "package-1",
        confirmation: "migration-1",
        reason: "Import Home migration package",
        confirmed: true,
      }),
    );
  });
});
