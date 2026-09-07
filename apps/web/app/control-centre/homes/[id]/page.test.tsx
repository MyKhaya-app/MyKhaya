import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import DetailPage from "./page";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useParams: () => ({ id: "home-1" }),
  usePathname: () => "/homes/home-1",
}));
vi.mock("@mykhaya/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@mykhaya/api-client")>();
  return {
    ...actual,
    platformApi: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  };
});
const { platformApi, ApiError } = await import("@mykhaya/api-client");
const get = platformApi.get as unknown as ReturnType<typeof vi.fn>;
const post = platformApi.post as unknown as ReturnType<typeof vi.fn>;
const put = platformApi.put as unknown as ReturnType<typeof vi.fn>;

const activeHome = {
  id: "home-1",
  name: "The Smiths",
  active: true,
  created_at: "2026-01-01T00:00:00Z",
  members: [{ user_id: "u1", display_name: "Jane Smith", email: "jane@example.com", role: "owner" }],
  pending_invitations: [{ id: "inv-1", email: "invitee@example.com", role: "member", expires_at: "2026-12-01T00:00:00Z" }],
  feature_overrides: [{ feature: "calendar", enabled: true }],
  notes: [{ id: "note-1", body: "Called about billing.", created_at: "2026-02-01T00:00:00Z" }],
};
const suspendedHome = { ...activeHome, active: false };
const emptyHome = { ...activeHome, members: [], pending_invitations: [], notes: [] };

function findDialog(name: RegExp | string) {
  return screen.findByRole("dialog", { name });
}

beforeEach(() => {
  vi.clearAllMocks();
  get.mockResolvedValue(activeHome);
  post.mockResolvedValue({ message: "ok" });
  put.mockResolvedValue({});
});

describe("Home detail", () => {
  it("renders home metadata and an Active status", async () => {
    render(<DetailPage />);
    expect(await screen.findByText("The Smiths")).toBeInTheDocument();
    expect(screen.getAllByText("Active").length).toBeGreaterThan(0);
    expect(screen.getByText("home-1")).toBeInTheDocument();
  });

  it("shows a Suspended status and a Reactivate action when the home is suspended", async () => {
    get.mockResolvedValue(suspendedHome);
    render(<DetailPage />);
    expect(await screen.findByText("The Smiths")).toBeInTheDocument();
    expect(screen.getAllByText("Suspended").length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: "Reactivate Home" })).toBeInTheDocument();
  });

  it("renders memberships, invitations and notes", async () => {
    render(<DetailPage />);
    await screen.findByText("The Smiths");
    expect(screen.getByText("Jane Smith")).toBeInTheDocument();
    expect(screen.getByText(/jane@example.com/)).toBeInTheDocument();
    expect(screen.getByText("invitee@example.com")).toBeInTheDocument();
    expect(screen.getByText("Called about billing.")).toBeInTheDocument();
  });

  it("shows empty states when there are no members, invitations or notes", async () => {
    get.mockResolvedValue(emptyHome);
    render(<DetailPage />);
    await screen.findByText("The Smiths");
    expect(screen.getByText("No members yet.")).toBeInTheDocument();
    expect(screen.getByText("No pending invitations.")).toBeInTheDocument();
    expect(screen.getByText("No administrative notes yet.")).toBeInTheDocument();
  });

  it("requires a reason of at least 10 characters before suspending, and sends the exact payload", async () => {
    render(<DetailPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Suspend Home" }));
    const dialog = await findDialog(/Suspend Home/i);
    const confirmButton = within(dialog).getByRole("button", { name: "Suspend Home" });
    const reasonInput = within(dialog).getByLabelText(/reason for this administrative action/i);
    expect(reasonInput).toHaveAttribute("minLength", "10");
    expect(reasonInput).toHaveAttribute("maxLength", "500");
    expect(reasonInput).toBeRequired();

    await userEvent.type(reasonInput, "Suspending pending a billing dispute");
    await userEvent.click(confirmButton);
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/homes/home-1/suspend", {
        reason: "Suspending pending a billing dispute",
        confirmed: true,
      }),
    );
  });

  it("reactivates symmetrically", async () => {
    get.mockResolvedValue(suspendedHome);
    render(<DetailPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Reactivate Home" }));
    const dialog = await findDialog(/Reactivate Home/i);
    await userEvent.type(within(dialog).getByLabelText(/reason for this administrative action/i), "Reactivating per request");
    await userEvent.click(within(dialog).getByRole("button", { name: "Reactivate Home" }));
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/homes/home-1/reactivate", {
        reason: "Reactivating per request",
        confirmed: true,
      }),
    );
  });

  it("requires confirmation and a reason to toggle a feature flag, and sends it to the exact endpoint", async () => {
    render(<DetailPage />);
    await screen.findByText("The Smiths");
    // calendar is enabled in the fixture, so its action is "Disable".
    const calendarRow = screen.getByText("calendar").closest("article")!;
    await userEvent.click(within(calendarRow).getByRole("button", { name: "Disable" }));
    const dialog = await findDialog(/Disable calendar/i);
    await userEvent.type(within(dialog).getByLabelText(/reason for this administrative action/i), "Turning off calendar module");
    await userEvent.click(within(dialog).getByRole("button", { name: "Disable" }));
    await waitFor(() =>
      expect(put).toHaveBeenCalledWith("/homes/home-1/feature-flags/calendar", {
        enabled: false,
        reason: "Turning off calendar module",
        confirmed: true,
      }),
    );
  });

  it("adds a note without requiring a reason and reloads", async () => {
    render(<DetailPage />);
    await screen.findByText("The Smiths");
    await userEvent.type(screen.getByLabelText("New internal note"), "A fresh note");
    await userEvent.click(screen.getByRole("button", { name: "Add administrative note" }));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/homes/home-1/notes", { body: "A fresh note" }));
    await waitFor(() =>
      expect(get.mock.calls.filter((call) => call[0] === "/homes/home-1")).toHaveLength(2),
    );
  });

  it("shows the reauth modal on a 403 and retries suspend after re-authenticating", async () => {
    post.mockImplementation((path: string) => {
      if (path === "/auth/reauthenticate") return Promise.resolve(undefined);
      if (path === "/homes/home-1/suspend") {
        const attempts = post.mock.calls.filter((call) => call[0] === "/homes/home-1/suspend").length;
        if (attempts === 1) return Promise.reject(new ApiError(403, "Recent administrator authentication required."));
        return Promise.resolve({ message: "Home suspended." });
      }
      return Promise.resolve({ message: "ok" });
    });
    render(<DetailPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Suspend Home" }));
    const dialog = await findDialog(/Suspend Home/i);
    await userEvent.type(within(dialog).getByLabelText(/reason for this administrative action/i), "Suspending for review");
    await userEvent.click(within(dialog).getByRole("button", { name: "Suspend Home" }));

    const reauthDialog = await screen.findByRole("dialog", { name: /Confirm it.?s you/i });
    await userEvent.type(within(reauthDialog).getByLabelText("Password"), "operator-password");
    await userEvent.click(within(reauthDialog).getByRole("button", { name: "Confirm" }));

    await waitFor(() => expect(screen.getByText("Home suspended.")).toBeInTheDocument());
    expect(post.mock.calls.filter((call) => call[0] === "/homes/home-1/suspend")).toHaveLength(2);
  });

  it("shows a safe error message when an action fails", async () => {
    post.mockRejectedValueOnce(new Error("Home not found"));
    render(<DetailPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Suspend Home" }));
    const dialog = await findDialog(/Suspend Home/i);
    await userEvent.type(within(dialog).getByLabelText(/reason for this administrative action/i), "Suspending for review");
    await userEvent.click(within(dialog).getByRole("button", { name: "Suspend Home" }));
    expect(await screen.findByText("Home not found")).toBeInTheDocument();
  });
});
