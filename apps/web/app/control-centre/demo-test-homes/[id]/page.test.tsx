import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import DetailPage from "./page";

const router = { push: vi.fn(), replace: vi.fn() };
vi.mock("next/navigation", () => ({ useRouter: () => router, useParams: () => ({ id: "1" }), usePathname: () => "/demo-test-homes/1" }));
vi.mock("@mykhaya/api-client", () => ({ platformApi: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() } }));
const { platformApi } = await import("@mykhaya/api-client");
const get = platformApi.get as unknown as ReturnType<typeof vi.fn>;
const post = platformApi.post as unknown as ReturnType<typeof vi.fn>;
const patch = platformApi.patch as unknown as ReturnType<typeof vi.fn>;
const del = platformApi.delete as unknown as ReturnType<typeof vi.fn>;
const home = { id: "1", fixture_key: "apple-review", display_name: "Apple Review Home", fixture_type: "apple_review", home_id: "h1", owner_user_id: "u1", status: "disabled", template_version: "1", expires_at: null, refreshed_at: null, created_at: "2026-09-07T09:00:00Z", created_by: "operator-1", disabled_at: "2026-09-07T10:00:00Z", account_email: "apple-review@mykhaya.app", email_verified: true, access: "family" };

beforeEach(() => { vi.clearAllMocks(); get.mockResolvedValue([home]); post.mockResolvedValue(home); patch.mockResolvedValue(home); del.mockResolvedValue(undefined); vi.spyOn(window, "confirm").mockReturnValue(true); });

describe("managed Demo/Test Home detail", () => {
  it("renders account, verification, entitlement, expiry and disabled state", async () => {
    render(<DetailPage />);
    expect(await screen.findByText("Apple Review Home")).toBeInTheDocument();
    expect(screen.getByText("apple-review@mykhaya.app")).toBeInTheDocument();
    expect(screen.getByText("Verified")).toBeInTheDocument();
    expect(screen.getByText("family")).toBeInTheDocument();
    expect(screen.getByText("disabled")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Enable" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Disable" })).not.toBeInTheDocument();
  });

  it("requires confirmation for refresh and delete, and sends scoped actions", async () => {
    render(<DetailPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Refresh / Reset" }));
    expect(window.confirm).toHaveBeenCalled();
    expect(post).toHaveBeenCalledWith("/demo-test-homes/1/refresh", expect.objectContaining({ confirmed: true }));
    await userEvent.click(screen.getByRole("button", { name: "Delete" }));
    expect(del).toHaveBeenCalledWith("/demo-test-homes/1", expect.objectContaining({ confirmed: true }));
  });

  it("validates and clears the reset-password fields", async () => {
    render(<DetailPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Reset Password" }));
    expect(screen.getByText("Reset password for apple-review@mykhaya.app")).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("New password"), "long-enough-password");
    await userEvent.type(screen.getByLabelText("Confirm password"), "long-enough-password");
    await userEvent.click(screen.getByRole("button", { name: /^Reset password$/ }));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/demo-test-homes/1/password", { password: "long-enough-password" }));
    expect(screen.queryByDisplayValue("long-enough-password")).not.toBeInTheDocument();
  });
});
