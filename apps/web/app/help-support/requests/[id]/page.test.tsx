import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import SupportRequestDetail from "./page";

// The route reads its id via `use(params)`, which suspends on first render
// until the params promise settles. render() itself isn't awaited by
// Testing Library, so the resulting suspend/resolve has to be wrapped in
// its own awaited act() or React warns and the DOM update is missed.
async function renderPage() {
  await act(async () => {
    render(<SupportRequestDetail params={params()} />);
  });
}

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  usePathname: () => "/help-support/requests/t1",
}));

vi.mock("@/components/use-active-home", () => ({
  useActiveHome: () => ({
    activeHome: { id: "home-1", name: "Hales Home", relationship: "home_admin" },
    activeHomeId: "home-1",
    homes: [{ id: "home-1", name: "Hales Home" }],
    setActiveHomeId: vi.fn(),
    loading: false,
  }),
}));

vi.mock("@mykhaya/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@mykhaya/api-client")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      me: vi.fn(),
      getSupportTicket: vi.fn(),
      addSupportTicketMessage: vi.fn(),
      closeSupportTicket: vi.fn(),
    },
  };
});

const { api, ApiError } = await import("@mykhaya/api-client");

const baseTicket = {
  id: "t1",
  reference: "MK-1001",
  type: "bug" as const,
  status: "open" as const,
  priority: "normal" as const,
  subject: "Calendar events disappearing",
  description: "Events vanish after saving them.",
  source: "ios" as const,
  app_area: "calendar",
  group_id: "home-1",
  created_at: "2026-09-01T09:00:00Z",
  updated_at: "2026-09-01T09:00:00Z",
  resolved_at: null,
  messages: [] as { id: string; author: "requester" | "admin"; message: string; created_at: string }[],
  attachments: [],
  diagnostics: null,
};

function params() {
  return Promise.resolve({ id: "t1" });
}

beforeEach(() => {
  vi.clearAllMocks();
  (api.me as ReturnType<typeof vi.fn>).mockResolvedValue({
    id: "u1",
    display_name: "Megan",
    principal_type: "adult",
  });
});

describe("Support request detail", () => {
  it("shows the original request", async () => {
    (api.getSupportTicket as ReturnType<typeof vi.fn>).mockResolvedValue(baseTicket);
    await renderPage();
    expect(await screen.findByText("Original request")).toBeInTheDocument();
    expect(screen.getByText("Events vanish after saving them.")).toBeInTheDocument();
    expect(screen.getAllByText("MK-1001").length).toBeGreaterThan(0);
    expect(screen.getByText("Open")).toBeInTheDocument();
  });

  it("renders the conversation in chronological order with You/MyKhaya Support labels, never admin names", async () => {
    (api.getSupportTicket as ReturnType<typeof vi.fn>).mockResolvedValue({
      ...baseTicket,
      messages: [
        { id: "m1", author: "requester", message: "Any update?", created_at: "2026-09-01T10:00:00Z" },
        { id: "m2", author: "admin", message: "We're looking into it.", created_at: "2026-09-01T11:00:00Z" },
        { id: "m3", author: "requester", message: "Thanks!", created_at: "2026-09-01T12:00:00Z" },
      ],
    });
    await renderPage();
    await screen.findByText("Any update?");
    const messages = screen.getAllByText(/Any update\?|We're looking into it\.|Thanks!/);
    expect(messages.map((el) => el.textContent)).toEqual([
      "Any update?",
      "We're looking into it.",
      "Thanks!",
    ]);
    const youLabels = screen.getAllByText("You");
    const supportLabels = screen.getAllByText("MyKhaya Support");
    expect(youLabels).toHaveLength(2);
    expect(supportLabels).toHaveLength(1);
  });

  it("allows a reply on an active ticket, disables duplicate submission, and shows it after sending", async () => {
    let resolveReply!: (value: unknown) => void;
    (api.getSupportTicket as ReturnType<typeof vi.fn>).mockResolvedValue(baseTicket);
    (api.addSupportTicketMessage as ReturnType<typeof vi.fn>).mockImplementation(
      () => new Promise((resolve) => { resolveReply = resolve; }),
    );
    const user = userEvent.setup();
    await renderPage();
    await screen.findByText("Original request");

    const textarea = screen.getByLabelText("Add a reply");
    await user.type(textarea, "Still happening.");
    const sendButton = screen.getByRole("button", { name: /send reply/i });
    await user.click(sendButton);

    expect(api.addSupportTicketMessage).toHaveBeenCalledTimes(1);
    expect(api.addSupportTicketMessage).toHaveBeenCalledWith("t1", { message: "Still happening." });
    expect(sendButton).toBeDisabled();

    // A second click while still sending must not fire a second request.
    await user.click(sendButton);
    expect(api.addSupportTicketMessage).toHaveBeenCalledTimes(1);

    (api.getSupportTicket as ReturnType<typeof vi.fn>).mockResolvedValue({
      ...baseTicket,
      messages: [{ id: "m1", author: "requester", message: "Still happening.", created_at: "2026-09-01T10:00:00Z" }],
    });
    resolveReply({});
    await waitFor(() => expect(screen.getByText("Still happening.")).toBeInTheDocument());
  });

  it("does not submit an empty or whitespace-only reply", async () => {
    (api.getSupportTicket as ReturnType<typeof vi.fn>).mockResolvedValue(baseTicket);
    const user = userEvent.setup();
    await renderPage();
    await screen.findByText("Original request");
    const sendButton = screen.getByRole("button", { name: /send reply/i });
    expect(sendButton).toBeDisabled();
    await user.type(screen.getByLabelText("Add a reply"), "   ");
    expect(sendButton).toBeDisabled();
    expect(api.addSupportTicketMessage).not.toHaveBeenCalled();
  });

  it("preserves the typed reply text when sending fails", async () => {
    (api.getSupportTicket as ReturnType<typeof vi.fn>).mockResolvedValue(baseTicket);
    (api.addSupportTicketMessage as ReturnType<typeof vi.fn>).mockRejectedValue(
      new ApiError(500, "Couldn’t send your reply. Please try again."),
    );
    const user = userEvent.setup();
    await renderPage();
    await screen.findByText("Original request");
    await user.type(screen.getByLabelText("Add a reply"), "Please help.");
    await user.click(screen.getByRole("button", { name: /send reply/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Couldn’t send your reply. Please try again.");
    expect(screen.getByLabelText("Add a reply")).toHaveValue("Please help.");
  });

  it("shows a resolved message, not a reply form, and offers Contact support again", async () => {
    (api.getSupportTicket as ReturnType<typeof vi.fn>).mockResolvedValue({
      ...baseTicket,
      status: "resolved",
      resolved_at: "2026-09-02T09:00:00Z",
    });
    await renderPage();
    await screen.findByText("This request has been resolved.");
    expect(screen.queryByLabelText("Add a reply")).toBeNull();
    expect(screen.getByRole("link", { name: /contact support again/i })).toHaveAttribute(
      "href",
      "/help-support/contact-support",
    );
  });

  it("shows a closed message, not a reply form, and never silently reopens the ticket", async () => {
    (api.getSupportTicket as ReturnType<typeof vi.fn>).mockResolvedValue({
      ...baseTicket,
      status: "closed",
    });
    await renderPage();
    await screen.findByText("This conversation is closed.");
    expect(screen.queryByLabelText("Add a reply")).toBeNull();
    expect(api.addSupportTicketMessage).not.toHaveBeenCalled();
  });

  it("shows a safe error, not a raw exception, when loading the ticket fails", async () => {
    (api.getSupportTicket as ReturnType<typeof vi.fn>).mockRejectedValue(
      new ApiError(404, "That support ticket could not be found."),
    );
    await renderPage();
    expect(await screen.findByRole("alert")).toHaveTextContent("That support ticket could not be found.");
  });
});

describe("Closing a support ticket", () => {
  const closeTicket = () => api.closeSupportTicket as unknown as ReturnType<typeof vi.fn>;
  const getTicket = () => api.getSupportTicket as unknown as ReturnType<typeof vi.fn>;

  it("asks for confirmation, closes the ticket and shows it as closed straight away", async () => {
    getTicket().mockResolvedValue({ ...baseTicket });
    closeTicket().mockResolvedValue({ ...baseTicket, status: "closed", resolved_at: "2026-09-02T09:00:00Z" });
    await renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Close ticket" }));
    const sheet = await screen.findByRole("dialog", { name: "Close this support ticket?" });
    expect(sheet).toHaveTextContent(
      "Are you sure you want to close this ticket? You can still view the conversation afterwards.",
    );
    const buttons = Array.from(sheet.querySelectorAll(".sheet-actions button")).map((button) => button.textContent);
    expect(buttons).toEqual(["Cancel", "Close ticket"]);
    await userEvent.click(sheet.querySelector<HTMLButtonElement>(".sheet-actions button:last-child")!);
    expect(closeTicket()).toHaveBeenCalledWith("t1");
    expect(await screen.findByText("Your support ticket has been closed.")).toBeInTheDocument();
    expect(screen.getByText("This conversation is closed.")).toBeInTheDocument();
    // No repeat closure and no reply form once closed.
    expect(screen.queryByRole("button", { name: "Close ticket" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Send reply" })).toBeNull();
    expect(screen.getByText("Events vanish after saving them.")).toBeInTheDocument();
  });

  it("cancelling leaves the ticket open", async () => {
    getTicket().mockResolvedValue({ ...baseTicket });
    await renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Close ticket" }));
    await userEvent.click(await screen.findByRole("button", { name: "Cancel" }));
    expect(closeTicket()).not.toHaveBeenCalled();
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(screen.getByRole("button", { name: "Send reply" })).toBeInTheDocument();
  });

  it("offers closing a resolved ticket but not a closed one", async () => {
    getTicket().mockResolvedValue({ ...baseTicket, status: "resolved" });
    await renderPage();
    expect(await screen.findByRole("button", { name: "Close ticket" })).toBeInTheDocument();
  });

  it("hides Close ticket for an already-closed ticket", async () => {
    getTicket().mockResolvedValue({ ...baseTicket, status: "closed" });
    await renderPage();
    await screen.findByText("This conversation is closed.");
    expect(screen.queryByRole("button", { name: "Close ticket" })).toBeNull();
  });

  it("keeps the sheet open with a safe message when closing fails", async () => {
    getTicket().mockResolvedValue({ ...baseTicket });
    closeTicket().mockRejectedValue(new ApiError(404, "That support ticket could not be found."));
    await renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Close ticket" }));
    const sheet = await screen.findByRole("dialog", { name: "Close this support ticket?" });
    await userEvent.click(sheet.querySelector<HTMLButtonElement>(".sheet-actions button:last-child")!);
    expect(await screen.findByRole("alert")).toHaveTextContent("That support ticket could not be found.");
    expect(screen.queryByText("Your support ticket has been closed.")).toBeNull();
  });
});
