import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { platformApi } from "@mykhaya/api-client";
import DocsSyncPage from "./page";

vi.mock("next/navigation", () => ({
  usePathname: () => "/docs-sync",
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
}));
vi.mock("@mykhaya/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@mykhaya/api-client")>();
  return { ...actual, platformApi: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() } };
});

const get = platformApi.get as unknown as ReturnType<typeof vi.fn>;
const actor = { id: "op-1", email: "op@mykhaya.app", display_name: "Operator", role: "platform_owner", mfa_enrolled: true, session_status: "full" as const };
const base = {
  environment: "development",
  branch: "dev",
  url: null,
  token_id: null,
  has_token_secret: false,
  repository_url: null,
  include_paths: [],
  shelf_id: null,
  shelf_name: null,
  auto_enabled: false,
  configured: false,
  connection: null,
  last_success_at: null,
  last_run: null,
  sync_requested: false,
  changes_pending: false,
  source: { available: true, documents: 117 },
};

function respond(overview: object) {
  get.mockImplementation((path: string) => {
    if (path === "/auth/me") return Promise.resolve(actor);
    if (path === "/docs-sync") return Promise.resolve(overview);
    if (path === "/docs-sync/shelves") return Promise.resolve({ shelves: [{ id: 7, name: "MyKhaya" }] });
    return Promise.reject(new Error("unexpected"));
  });
}

beforeEach(() => vi.clearAllMocks());

describe("Documentation Sync page", () => {
  it("starts unconfigured with sync actions disabled and the branch shown", async () => {
    respond(base);
    render(<DocsSyncPage />);
    expect(await screen.findByText(/dev branch, development/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sync now" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Enable automatic sync" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Test connection" })).toBeDisabled();
  });

  it("never renders a token secret and shows the last run counts", async () => {
    respond({
      ...base,
      url: "https://docs.example.com",
      token_id: "tid",
      has_token_secret: true,
      shelf_id: 7,
      shelf_name: "MyKhaya",
      configured: true,
      auto_enabled: true,
      last_run: { status: "succeeded", trigger: "automatic", finished_at: "2026-11-09T20:00:00Z", created: 3, updated: 1, skipped: 113 },
    });
    render(<DocsSyncPage />);
    expect(await screen.findByText("3 / 1 / 113")).toBeInTheDocument();
    const secret = screen.getByLabelText<HTMLInputElement>(/API token secret/);
    expect(secret.value).toBe("");
    expect(secret.type).toBe("password");
    expect(screen.getByRole("button", { name: "Sync now" })).toBeEnabled();
  });

  it("populates the destination dropdown from BookStack on refresh", async () => {
    respond({ ...base, url: "https://docs.example.com", token_id: "tid", has_token_secret: true });
    render(<DocsSyncPage />);
    (await screen.findByRole("button", { name: "Refresh shelves" })).click();
    expect(await screen.findByRole("option", { name: "MyKhaya" })).toBeInTheDocument();
  });
});
