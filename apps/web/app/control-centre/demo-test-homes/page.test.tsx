import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import DemoTestHomesPage from "./page";

const router = { push: vi.fn(), replace: vi.fn() };
vi.mock("next/navigation", () => ({ useRouter: () => router, usePathname: () => "/demo-test-homes" }));
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

const rows = [{ id: "1", fixture_key: "apple-review", display_name: "Apple Review Home", fixture_type: "apple_review", home_id: "h1", owner_user_id: "u1", status: "enabled", template_version: "1", expires_at: null, refreshed_at: "2026-09-07T10:00:00Z", created_at: "2026-09-07T09:00:00Z", created_by: null, disabled_at: null, account_email: "apple-review@mykhaya.app", email_verified: true, access: "family" }];

beforeEach(() => { vi.clearAllMocks(); get.mockImplementation((path: string) => path === "/auth/me" ? Promise.resolve({ id: "op", email: "op@example.com", display_name: "Operator", role: "platform_owner", mfa_enrolled: true, session_status: "full" }) : Promise.resolve(rows)); post.mockResolvedValue({ ...rows[0], id: "new" }); });

describe("Demo & Test Homes PCC list", () => {
  it("renders the table with status, verification and family-access badges", async () => {
    render(<DemoTestHomesPage />);
    expect(await screen.findByText("Apple Review Home")).toBeInTheDocument();
    expect(screen.getByText("Apple Review")).toBeInTheDocument();
    expect(screen.getByText("Enabled")).toBeInTheDocument();
    expect(screen.getByText("Verified")).toBeInTheDocument();
    expect(screen.getByText("Family")).toBeInTheDocument();
    expect(screen.getByText("apple-review@mykhaya.app")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Apple Review Home" })).toHaveAttribute("href", "/demo-test-homes/1");
  });

  it("opens the create form and shows the pre-verified explanation", async () => {
    render(<DemoTestHomesPage />);
    await userEvent.click(await screen.findByRole("button", { name: /create demo\/test home/i }));
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

  it("shows a safe error message when creation fails", async () => {
    post.mockRejectedValueOnce(new Error("Fixture key already in use."));
    render(<DemoTestHomesPage />);
    await userEvent.click(await screen.findByRole("button", { name: /create demo\/test home/i }));
    await userEvent.type(screen.getByLabelText("Fixture key"), "family-demo");
    await userEvent.type(screen.getByLabelText("Home name"), "Family Demo");
    await userEvent.type(screen.getByLabelText("Account email"), "demo@example.com");
    await userEvent.type(screen.getByLabelText("New password"), "long-enough-password");
    await userEvent.type(screen.getByLabelText("Confirm password"), "long-enough-password");
    await userEvent.click(screen.getByRole("button", { name: /^Create$/ }));
    expect(await screen.findByText("Fixture key already in use.")).toBeInTheDocument();
    expect(router.push).not.toHaveBeenCalled();
  });

  it("shows the reauth modal on a 403 recent-auth error and retries creation after re-authenticating", async () => {
    post.mockImplementation((path: string) => {
      if (path === "/auth/reauthenticate") return Promise.resolve(undefined);
      if (path === "/demo-test-homes") {
        if (post.mock.calls.filter((call) => call[0] === "/demo-test-homes").length === 1) {
          return Promise.reject(new ApiError(403, "Recent administrator authentication required."));
        }
        return Promise.resolve({ ...rows[0], id: "new" });
      }
      return Promise.resolve(undefined);
    });
    render(<DemoTestHomesPage />);
    await userEvent.click(await screen.findByRole("button", { name: /create demo\/test home/i }));
    await userEvent.type(screen.getByLabelText("Fixture key"), "family-demo");
    await userEvent.type(screen.getByLabelText("Home name"), "Family Demo");
    await userEvent.type(screen.getByLabelText("Account email"), "demo@example.com");
    await userEvent.type(screen.getByLabelText("New password"), "long-enough-password");
    await userEvent.type(screen.getByLabelText("Confirm password"), "long-enough-password");
    await userEvent.click(screen.getByRole("button", { name: /^Create$/ }));

    const reauthDialog = await screen.findByRole("dialog", { name: /Confirm it.?s you/i });
    await userEvent.type(within(reauthDialog).getByLabelText("Password"), "operator-password");
    await userEvent.click(within(reauthDialog).getByRole("button", { name: "Confirm" }));

    await waitFor(() => expect(router.push).toHaveBeenCalledWith("/demo-test-homes/new"));
    expect(post).toHaveBeenCalledWith("/auth/reauthenticate", { password: "operator-password" });
  });

  describe("showcase templates", () => {
    const templates = [
      { fixture_type: "apple_review", label: "Apple Review", access: "family", showcase: false, showcase_modules: [] },
      {
        fixture_type: "demo",
        label: "Family Demo",
        access: "family",
        showcase: true,
        showcase_modules: [
          { key: "calendar", name: "Calendar" },
          { key: "meals", name: "Meal Plans" },
        ],
      },
      {
        fixture_type: "ultimate_demo",
        label: "Ultimate Demo",
        access: "ultimate",
        showcase: true,
        showcase_modules: [
          { key: "calendar", name: "Calendar" },
          { key: "budget", name: "Budget" },
          { key: "driveway", name: "Driveway" },
        ],
      },
      { fixture_type: "free_demo", label: "Free Plan Demo", access: "free", showcase: false, showcase_modules: [] },
    ];
    const ultimateRow = { ...rows[0], id: "2", display_name: "The Parker Family", fixture_type: "ultimate_demo", access: "ultimate" };

    beforeEach(() => {
      get.mockImplementation((path: string) => {
        if (path === "/auth/me") return Promise.resolve({ id: "op", email: "op@example.com", display_name: "Operator", role: "platform_owner", mfa_enrolled: true, session_status: "full" });
        if (path === "/demo-test-homes/templates") return Promise.resolve(templates);
        return Promise.resolve([...rows, ultimateRow]);
      });
    });

    async function openFormAndFill() {
      render(<DemoTestHomesPage />);
      await userEvent.click(await screen.findByRole("button", { name: /create demo\/test home/i }));
      await screen.findByRole("option", { name: "Ultimate Demo" });
      await userEvent.type(screen.getByLabelText("Fixture key"), "parker-ultimate");
      await userEvent.type(screen.getByLabelText("Home name"), "The Parker Family");
      await userEvent.type(screen.getByLabelText("Account email"), "demo@example.com");
      await userEvent.type(screen.getByLabelText("New password"), "long-enough-password");
      await userEvent.type(screen.getByLabelText("Confirm password"), "long-enough-password");
    }

    it("lists all four templates and shows Ultimate plan access", async () => {
      render(<DemoTestHomesPage />);
      expect(await screen.findByText("The Parker Family")).toBeInTheDocument();
      expect(screen.getAllByText("Ultimate").length).toBeGreaterThan(0);
      await userEvent.click(screen.getByRole("button", { name: /create demo\/test home/i }));
      await waitFor(() =>
        expect(within(screen.getByLabelText("Template")).getAllByRole("option").map((option) => option.textContent)).toEqual([
          "Apple Review",
          "Family Demo",
          "Ultimate Demo",
          "Free Plan Demo",
        ]),
      );
      // Non-showcase templates show no showcase options.
      expect(screen.queryByLabelText("Populate with showcase data")).not.toBeInTheDocument();
    });

    it("explains the showcase and lists server-derived modules for the selected plan", async () => {
      await openFormAndFill();
      await userEvent.selectOptions(screen.getByLabelText("Template"), "ultimate_demo");
      expect(screen.getByText(/Emma, James, Sophie and Oliver Parker/)).toBeInTheDocument();
      expect(screen.getByText(/Calendar, Budget, Driveway/)).toBeInTheDocument();
      expect(screen.getByLabelText("Populate with showcase data")).toBeChecked();
      await userEvent.selectOptions(screen.getByLabelText("Template"), "demo");
      expect(screen.getByText(/Calendar, Meal Plans/)).toBeInTheDocument();
      expect(screen.queryByText(/Budget/)).not.toBeInTheDocument();
    });

    it("creates a populated showcase with rolling dates by default", async () => {
      await openFormAndFill();
      await userEvent.selectOptions(screen.getByLabelText("Template"), "ultimate_demo");
      await userEvent.click(screen.getByRole("button", { name: /^Create$/ }));
      await waitFor(() =>
        expect(post).toHaveBeenCalledWith(
          "/demo-test-homes",
          expect.objectContaining({ fixture_type: "ultimate_demo", populate_showcase: true, showcase_reference_date: null }),
        ),
      );
    });

    it("sends a pinned reference date in screenshot mode", async () => {
      await openFormAndFill();
      await userEvent.selectOptions(screen.getByLabelText("Template"), "demo");
      await userEvent.click(screen.getByLabelText(/Pin dates to a reference date/));
      const dateInput = screen.getByLabelText("Reference date");
      await userEvent.clear(dateInput);
      await userEvent.type(dateInput, "2026-11-04");
      await userEvent.click(screen.getByRole("button", { name: /^Create$/ }));
      await waitFor(() =>
        expect(post).toHaveBeenCalledWith(
          "/demo-test-homes",
          expect.objectContaining({ fixture_type: "demo", populate_showcase: true, showcase_reference_date: "2026-11-04" }),
        ),
      );
    });

    it("can create a clean, unpopulated Home on the same plan", async () => {
      await openFormAndFill();
      await userEvent.selectOptions(screen.getByLabelText("Template"), "ultimate_demo");
      await userEvent.click(screen.getByLabelText("Populate with showcase data"));
      expect(screen.getByText(/Creates a clean Home with genuine Ultimate access/)).toBeInTheDocument();
      await userEvent.click(screen.getByRole("button", { name: /^Create$/ }));
      await waitFor(() =>
        expect(post).toHaveBeenCalledWith(
          "/demo-test-homes",
          expect.objectContaining({ fixture_type: "ultimate_demo", populate_showcase: false }),
        ),
      );
    });
  });

  it("shows an empty state when there are no managed Homes", async () => {
    get.mockImplementation((path: string) => path === "/auth/me" ? Promise.resolve({ id: "op", email: "op@example.com", display_name: "Operator", role: "platform_owner", mfa_enrolled: true, session_status: "full" }) : Promise.resolve([]));
    render(<DemoTestHomesPage />);
    expect(await screen.findByText("No managed Demo/Test Homes.")).toBeInTheDocument();
  });

  it("shows a safe error message when the list fails to load", async () => {
    get.mockImplementation((path: string) => path === "/auth/me" ? Promise.resolve({ id: "op", email: "op@example.com", display_name: "Operator", role: "platform_owner", mfa_enrolled: true, session_status: "full" }) : Promise.reject(new Error("Service unavailable.")));
    render(<DemoTestHomesPage />);
    expect(await screen.findByText("Service unavailable.")).toBeInTheDocument();
  });
});
