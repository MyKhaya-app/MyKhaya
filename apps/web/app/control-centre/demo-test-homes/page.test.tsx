import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import DemoTestHomesPage from "./page";

const router = { push: vi.fn(), replace: vi.fn() };
vi.mock("next/navigation", () => ({ useRouter: () => router, usePathname: () => "/demo-test-homes" }));
vi.mock("@mykhaya/api-client", () => ({ platformApi: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() } }));
const { platformApi } = await import("@mykhaya/api-client");
const get = platformApi.get as unknown as ReturnType<typeof vi.fn>;
const post = platformApi.post as unknown as ReturnType<typeof vi.fn>;

const rows = [{ id: "1", fixture_key: "apple-review", display_name: "Apple Review Home", fixture_type: "apple_review", home_id: "h1", owner_user_id: "u1", status: "enabled", template_version: "1", expires_at: null, refreshed_at: "2026-09-07T10:00:00Z", created_at: "2026-09-07T09:00:00Z", created_by: null, disabled_at: null, account_email: "apple-review@mykhaya.app", email_verified: true, access: "family" }];

beforeEach(() => { vi.clearAllMocks(); get.mockImplementation((path: string) => path === "/auth/me" ? Promise.resolve({ id: "op", email: "op@example.com", display_name: "Operator", role: "platform_owner", mfa_enrolled: true, session_status: "full" }) : Promise.resolve(rows)); post.mockResolvedValue({ ...rows[0], id: "new" }); });

describe("Demo & Test Homes PCC list", () => {
  it("renders navigation content, Apple Review, Family access and create controls", async () => {
    render(<DemoTestHomesPage />);
    expect(await screen.findByText("Apple Review Home")).toBeInTheDocument();
    expect(screen.getByText("Apple Review")).toBeInTheDocument();
    expect(screen.getByText("family")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /create demo\/test home/i }));
    expect(screen.getByText(/provisioned as verified managed accounts/i)).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Apple Review" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Family Demo" })).toBeInTheDocument();
    expect(screen.getByLabelText("New password")).toBeInTheDocument();
    expect(screen.getByLabelText("Confirm password")).toBeInTheDocument();
  });

  it("blocks mismatched create passwords and does not call the API", async () => {
    render(<DemoTestHomesPage />);
    await userEvent.click(await screen.findByRole("button", { name: /create demo\/test home/i }));
    await userEvent.type(screen.getByLabelText("Fixture key"), "family-demo");
    await userEvent.type(screen.getByLabelText("Home name"), "Family Demo");
    await userEvent.type(screen.getByLabelText("Account email"), "demo@example.com");
    await userEvent.type(screen.getByLabelText("New password"), "long-enough-password");
    await userEvent.type(screen.getByLabelText("Confirm password"), "different-password");
    await userEvent.click(screen.getByRole("button", { name: /^Create$/ }));
    expect(await screen.findByText(/passwords must match/i)).toBeInTheDocument();
    expect(post).not.toHaveBeenCalledWith("/demo-test-homes", expect.anything());
  });

  it("navigates to the managed detail page after creation", async () => {
    render(<DemoTestHomesPage />);
    await userEvent.click(await screen.findByRole("button", { name: /create demo\/test home/i }));
    await userEvent.type(screen.getByLabelText("Fixture key"), "family-demo");
    await userEvent.type(screen.getByLabelText("Home name"), "Family Demo");
    await userEvent.type(screen.getByLabelText("Account email"), "demo@example.com");
    await userEvent.type(screen.getByLabelText("New password"), "long-enough-password");
    await userEvent.type(screen.getByLabelText("Confirm password"), "long-enough-password");
    await userEvent.click(screen.getByRole("button", { name: /^Create$/ }));
    await waitFor(() => expect(router.push).toHaveBeenCalledWith("/demo-test-homes/new"));
    expect(post).toHaveBeenCalledWith("/demo-test-homes", expect.objectContaining({ fixture_type: "apple_review", password: "long-enough-password" }));
  });
});
