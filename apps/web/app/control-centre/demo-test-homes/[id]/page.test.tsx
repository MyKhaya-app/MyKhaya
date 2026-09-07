import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import DetailPage from "./page";

const router = { push: vi.fn(), replace: vi.fn() };
vi.mock("next/navigation", () => ({ useRouter: () => router, useParams: () => ({ id: "1" }), usePathname: () => "/demo-test-homes/1" }));
vi.mock("@mykhaya/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@mykhaya/api-client")>();
  return {
    ...actual,
    platformApi: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  };
});
const { platformApi, ApiError } = await import("@mykhaya/api-client");
const get = platformApi.get as unknown as ReturnType<typeof vi.fn>;
const post = platformApi.post as unknown as ReturnType<typeof vi.fn>;
const patch = platformApi.patch as unknown as ReturnType<typeof vi.fn>;
const del = platformApi.delete as unknown as ReturnType<typeof vi.fn>;

const disabledHome = { id: "1", fixture_key: "apple-review", display_name: "Apple Review Home", fixture_type: "apple_review" as const, home_id: "h1", owner_user_id: "u1", status: "disabled" as const, template_version: "1", expires_at: null, refreshed_at: null, created_at: "2026-09-07T09:00:00Z", created_by: "operator-1", disabled_at: "2026-09-07T10:00:00Z", account_email: "apple-review@mykhaya.app", email_verified: true, access: "family" as const };
const enabledHome = { ...disabledHome, status: "enabled" as const, disabled_at: null };
const expiredHome = { ...disabledHome, status: "expired" as const, expires_at: "2026-01-01T00:00:00Z" };

function findDialog(name: RegExp | string) {
  return screen.findByRole("dialog", { name });
}

beforeEach(() => {
  vi.clearAllMocks();
  get.mockResolvedValue([disabledHome]);
  post.mockResolvedValue(disabledHome);
  patch.mockResolvedValue(disabledHome);
  del.mockResolvedValue(undefined);
});

describe("managed Demo/Test Home detail", () => {
  it("renders home details metadata and a Disabled status card, with Enable available", async () => {
    render(<DetailPage />);
    expect(await screen.findByText("Apple Review Home")).toBeInTheDocument();
    expect(screen.getByText("apple-review@mykhaya.app")).toBeInTheDocument();
    expect(screen.getByText("Verified")).toBeInTheDocument();
    expect(screen.getAllByText("Family").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Disabled").length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: /^Enable$/ })).toBeEnabled();
    expect(screen.queryByRole("button", { name: /^Disable$/ })).not.toBeInTheDocument();
  });

  it("shows an Enabled status card with Disable available when the home is enabled", async () => {
    get.mockResolvedValue([enabledHome]);
    render(<DetailPage />);
    expect(await screen.findByText("Apple Review Home")).toBeInTheDocument();
    expect(screen.getAllByText("Enabled").length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: /^Enable$/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: /^Disable$/ })).toBeInTheDocument();
  });

  it("shows an Expired status card without implying active access", async () => {
    get.mockResolvedValue([expiredHome]);
    render(<DetailPage />);
    expect(await screen.findByText("Apple Review Home")).toBeInTheDocument();
    expect(screen.getAllByText(/Expired/).length).toBeGreaterThan(0);
    // Expired homes are not enabled — Enable stays available, Disable is not shown.
    expect(screen.getByRole("button", { name: /^Enable$/ })).toBeEnabled();
    expect(screen.queryByRole("button", { name: /^Disable$/ })).not.toBeInTheDocument();
  });

  it("confirms Enable via a lightweight dialog and calls the enable endpoint", async () => {
    render(<DetailPage />);
    await userEvent.click(await screen.findByRole("button", { name: /^Enable$/ }));
    const dialog = await findDialog(/Enable Demo\/Test Home/i);
    expect(within(dialog).getByText("Enable Apple Review Home?")).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: /^Enable$/ }));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/demo-test-homes/1/enable", {}));
  });

  it("requires the exact Disable confirmation copy and a reason before disabling", async () => {
    get.mockResolvedValue([enabledHome]);
    render(<DetailPage />);
    await userEvent.click(await screen.findByRole("button", { name: /^Disable$/ }));
    const dialog = await findDialog(/Disable Demo\/Test account/i);
    expect(
      within(dialog).getByText(
        "Disable this Demo/Test account? The Home and its data will be retained, but the managed account will no longer be able to sign in.",
      ),
    ).toBeInTheDocument();
    await userEvent.type(within(dialog).getByLabelText(/reason for this administrative action/i), "Operator requested pause");
    await userEvent.click(within(dialog).getByRole("button", { name: /^Disable$/ }));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/demo-test-homes/1/disable", {}));
  });

  it("requires confirmation and a reason for refresh, and sends it as the audit reason", async () => {
    render(<DetailPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Refresh / Reset" }));
    const dialog = await findDialog(/Refresh \/ Reset Demo\/Test Home/i);
    expect(
      within(dialog).getByText(
        "Refreshing this Demo/Test Home will reset it to the template state and remove changes made during testing.",
      ),
    ).toBeInTheDocument();
    await userEvent.type(within(dialog).getByLabelText(/reason for this administrative action/i), "QA regression pass");
    await userEvent.click(within(dialog).getByRole("button", { name: /^Refresh \/ Reset$/ }));
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/demo-test-homes/1/refresh", { reason: "QA regression pass", confirmed: true }),
    );
  });

  it("requires confirmation and a reason for delete, and redirects to the list on success", async () => {
    render(<DetailPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Delete" }));
    const dialog = await findDialog(/Delete Demo\/Test Home/i);
    expect(
      within(dialog).getByText(
        "Delete this Demo/Test Home? This permanently removes the managed environment and its fixture-owned data. This cannot be undone.",
      ),
    ).toBeInTheDocument();
    await userEvent.type(within(dialog).getByLabelText(/reason for this administrative action/i), "Cleaning up test fixture");
    await userEvent.click(within(dialog).getByRole("button", { name: "Delete" }));
    await waitFor(() =>
      expect(del).toHaveBeenCalledWith("/demo-test-homes/1", { reason: "Cleaning up test fixture", confirmed: true }),
    );
    await waitFor(() => expect(router.push).toHaveBeenCalledWith("/demo-test-homes"));
  });

  it("shows the target account and blocks a mismatched/too-short reset password without calling the API", async () => {
    render(<DetailPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Reset Password" }));
    const dialog = await findDialog(/Reset password for apple-review@mykhaya\.app/i);
    await userEvent.type(within(dialog).getByLabelText("New password"), "short");
    await userEvent.type(within(dialog).getByLabelText("Confirm password"), "short");
    await userEvent.click(within(dialog).getByRole("button", { name: /^Reset password$/ }));
    expect(await within(dialog).findByText(/passwords must match/i)).toBeInTheDocument();
    expect(post).not.toHaveBeenCalledWith("/demo-test-homes/1/password", expect.anything());
  });

  it("submits and clears the reset-password dialog on a valid, matching password", async () => {
    render(<DetailPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Reset Password" }));
    const dialog = await findDialog(/Reset password for apple-review@mykhaya\.app/i);
    await userEvent.type(within(dialog).getByLabelText("New password"), "long-enough-password");
    await userEvent.type(within(dialog).getByLabelText("Confirm password"), "long-enough-password");
    await userEvent.click(within(dialog).getByRole("button", { name: /^Reset password$/ }));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/demo-test-homes/1/password", { password: "long-enough-password" }));
    expect(screen.queryByDisplayValue("long-enough-password")).not.toBeInTheDocument();
  });

  it("sets and removes the expiry without implicitly changing enabled state", async () => {
    render(<DetailPage />);
    await screen.findByText("Apple Review Home");
    const expiryInput = screen.getByLabelText("Set or change expiry");
    await userEvent.type(expiryInput, "2026-12-01T10:00");
    await userEvent.click(screen.getByRole("button", { name: /^Save expiry$/ }));
    await waitFor(() =>
      expect(patch).toHaveBeenCalledWith("/demo-test-homes/1/expiry", { expires_at: new Date("2026-12-01T10:00").toISOString() }),
    );
    // Saving/removing expiry must never itself call enable/disable.
    expect(post).not.toHaveBeenCalledWith(expect.stringContaining("/enable"), expect.anything());
    expect(post).not.toHaveBeenCalledWith(expect.stringContaining("/disable"), expect.anything());

    get.mockResolvedValue([{ ...disabledHome, expires_at: "2026-12-01T10:00:00Z" }]);
    await userEvent.click(screen.getByRole("button", { name: /^Remove expiry$/ }));
    await waitFor(() => expect(screen.getByLabelText("Set or change expiry")).toHaveValue(""));
  });

  it("disables the action bar while a request is pending", async () => {
    let resolveEnable: (() => void) | undefined;
    post.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveEnable = () => resolve(disabledHome);
        }),
    );
    render(<DetailPage />);
    await userEvent.click(await screen.findByRole("button", { name: /^Enable$/ }));
    const dialog = await findDialog(/Enable Demo\/Test Home/i);
    await userEvent.click(within(dialog).getByRole("button", { name: /^Enable$/ }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Refresh / Reset" })).toBeDisabled());
    resolveEnable?.();
    await waitFor(() => expect(screen.getByRole("button", { name: "Refresh / Reset" })).toBeEnabled());
  });

  it("shows the reauth modal on a 403 recent-auth error and retries the action after re-authenticating", async () => {
    post.mockImplementation((path: string) => {
      if (path === "/auth/reauthenticate") return Promise.resolve(undefined);
      if (path === "/demo-test-homes/1/enable") {
        const priorAttempts = post.mock.calls.filter((call) => call[0] === "/demo-test-homes/1/enable").length;
        if (priorAttempts === 1) {
          return Promise.reject(new ApiError(403, "Recent administrator authentication required."));
        }
        return Promise.resolve(enabledHome);
      }
      return Promise.resolve(disabledHome);
    });
    render(<DetailPage />);
    await userEvent.click(await screen.findByRole("button", { name: /^Enable$/ }));
    const dialog = await findDialog(/Enable Demo\/Test Home/i);
    await userEvent.click(within(dialog).getByRole("button", { name: /^Enable$/ }));

    const reauthDialog = await screen.findByRole("dialog", { name: /Confirm it.?s you/i });
    await userEvent.type(within(reauthDialog).getByLabelText("Password"), "operator-password");
    await userEvent.click(within(reauthDialog).getByRole("button", { name: "Confirm" }));

    await waitFor(() => expect(screen.getByText("Demo/Test Home enabled.")).toBeInTheDocument());
    expect(post).toHaveBeenCalledWith("/auth/reauthenticate", { password: "operator-password" });
    expect(post.mock.calls.filter((call) => call[0] === "/demo-test-homes/1/enable")).toHaveLength(2);
  });

  it("shows a safe error notice when an action fails", async () => {
    post.mockRejectedValueOnce(new Error("Managed Home not found"));
    render(<DetailPage />);
    await userEvent.click(await screen.findByRole("button", { name: /^Enable$/ }));
    const dialog = await findDialog(/Enable Demo\/Test Home/i);
    await userEvent.click(within(dialog).getByRole("button", { name: /^Enable$/ }));
    expect(await screen.findByText("Managed Home not found")).toBeInTheDocument();
  });
});
