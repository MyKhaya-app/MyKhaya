import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ContactSupport from "./page";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  usePathname: () => "/help-support/contact-support",
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
  return { ...actual, api: { ...actual.api, me: vi.fn(), createSupportTicket: vi.fn(), uploadSupportAttachment: vi.fn() } };
});

vi.mock("@/components/use-notification-permission", () => ({
  useNotificationPermission: () => ({ status: "granted", loading: false }),
}));

const { api } = await import("@mykhaya/api-client");

beforeEach(() => {
  vi.clearAllMocks();
  (api.me as ReturnType<typeof vi.fn>).mockResolvedValue({
    id: "u1",
    display_name: "Megan",
    principal_type: "adult",
  });
  global.fetch = vi.fn((input: RequestInfo | URL) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    if (url.includes("config/public")) return Promise.resolve({ ok: true, json: () => Promise.resolve({ support_enabled: true }) });
    return Promise.resolve({ ok: true, json: () => Promise.resolve({ version: "1.0.0", build_time: "1" }) });
  }) as unknown as typeof fetch;
});

describe("Contact support", () => {
  it("renders the request form with diagnostics off by default", async () => {
    render(<ContactSupport />);
    await screen.findByRole("heading", { name: "Contact support" });
    expect(screen.getByLabelText("Subject")).toBeInTheDocument();
    expect(screen.getByLabelText("Message")).toBeInTheDocument();
    expect(screen.getByLabelText("Include diagnostics")).not.toBeChecked();
    expect(document.querySelector('a[href^="mailto:"]')).toBeNull();
  });

  it("shows a screenshot privacy warning visibly, before any file is chosen", async () => {
    render(<ContactSupport />);
    await screen.findByRole("heading", { name: "Contact support" });
    expect(
      screen.getByText("Your screenshot may include information currently visible on your screen."),
    ).toBeVisible();
  });

  it("shows a styled Add screenshot control, and swaps to a filename with Remove once a file is chosen", async () => {
    const user = userEvent.setup();
    render(<ContactSupport />);
    await screen.findByRole("heading", { name: "Contact support" });
    expect(screen.getByLabelText(/add screenshot/i)).toBeInTheDocument();
    expect(screen.queryByText("Remove")).toBeNull();

    const file = new File(["fake-image-bytes"], "screenshot.png", { type: "image/png" });
    const input = document.getElementById("contact-support-screenshot") as HTMLInputElement;
    await user.upload(input, file);

    expect(screen.getByText("screenshot.png")).toBeInTheDocument();
    expect(screen.getByLabelText(/change screenshot/i)).toBeInTheDocument();
    const removeButton = screen.getByRole("button", { name: "Remove" });
    await user.click(removeButton);
    expect(screen.queryByText("screenshot.png")).toBeNull();
    expect(input.value).toBe("");
  });

  it("submits a support ticket and shows its reference", async () => {
    const user = userEvent.setup();
    const createTicket = api.createSupportTicket as unknown as ReturnType<typeof vi.fn>;
    createTicket.mockResolvedValue({ id: "t1", reference: "MK-1042" });
    render(<ContactSupport />);
    await user.type(await screen.findByLabelText("Subject"), "Account help");
    await user.type(screen.getByLabelText("Message"), "I need help with my account.");
    await user.click(screen.getByRole("button", { name: /send request/i }));
    await waitFor(() => expect(createTicket).toHaveBeenCalled());
    expect(await screen.findByText("MK-1042")).toBeInTheDocument();
  });

  it("shows an empty subject and message on their own fields, focuses the first and sends nothing", async () => {
    const user = userEvent.setup();
    const createTicket = api.createSupportTicket as unknown as ReturnType<typeof vi.fn>;
    render(<ContactSupport />);
    const subject = await screen.findByLabelText("Subject");
    await user.type(screen.getByLabelText("Message"), "   ");
    await user.click(screen.getByRole("button", { name: /send request/i }));
    expect(await screen.findByText("Add a subject.")).toBeInTheDocument();
    expect(screen.getByText("Add a message.")).toBeInTheDocument();
    expect(subject).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByLabelText("Message")).toHaveAttribute("aria-invalid", "true");
    await waitFor(() => expect(subject).toHaveFocus());
    expect(createTicket).not.toHaveBeenCalled();
  });

  it("keeps the draft and shows the failure before the send button", async () => {
    const user = userEvent.setup();
    const createTicket = api.createSupportTicket as unknown as ReturnType<typeof vi.fn>;
    createTicket.mockRejectedValue(new Error("Support is busy"));
    render(<ContactSupport />);
    await user.type(await screen.findByLabelText("Subject"), "Account help");
    await user.type(screen.getByLabelText("Message"), "I need help with my account.");
    const send = screen.getByRole("button", { name: /send request/i });
    await user.click(send);
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Support is busy");
    expect(alert.compareDocumentPosition(send) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getByLabelText("Subject")).toHaveValue("Account help");
    expect(send).toBeEnabled();
  });
});
