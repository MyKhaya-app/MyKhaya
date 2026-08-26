import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import NotificationTestCentrePage from "./page";

const stableRouter = { replace: vi.fn(), push: vi.fn() };
vi.mock("next/navigation", () => ({
  usePathname: () => "/control-centre/notifications/test-centre",
  useRouter: () => stableRouter,
}));

vi.mock("@mykhaya/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@mykhaya/api-client")>();
  return {
    ...actual,
    platformApi: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  };
});

const { platformApi } = await import("@mykhaya/api-client");
const get = platformApi.get as unknown as ReturnType<typeof vi.fn>;
const post = platformApi.post as unknown as ReturnType<typeof vi.fn>;

const actor = {
  id: "op-1",
  email: "op@mykhaya.app",
  display_name: "Operator One",
  role: "platform_owner",
  mfa_enrolled: true,
  session_status: "full" as const,
};

const templates = [
  { template_type: "email_verification", module: "security", channel: "email" },
  { template_type: "calendar.event.reminder", module: "calendar", channel: "in_app" },
];

const usersPage = {
  items: [
    { id: "user-1", email: "megan@example.com", display_name: "Megan" },
    { id: "user-2", email: "sam@example.com", display_name: "Sam" },
  ],
};

function mockRoutes() {
  get.mockImplementation((path: string) => {
    if (path === "/auth/me") return Promise.resolve(actor);
    if (path === "/notification-templates") return Promise.resolve(templates);
    if (path.startsWith("/users?")) return Promise.resolve(usersPage);
    return Promise.reject(new Error(`unexpected path ${path}`));
  });
}

beforeEach(() => {
  get.mockReset();
  post.mockReset();
});

afterEach(() => {
  vi.restoreAllMocks();
});

async function fillOutForm(user: ReturnType<typeof userEvent.setup>) {
  await user.selectOptions(screen.getByLabelText("Template"), "email_verification");
  await user.type(screen.getByLabelText("Find recipient"), "megan");
  await user.click(screen.getByRole("button", { name: "Search" }));
  await user.selectOptions(await screen.findByLabelText("Recipient"), "user-1");
  await user.type(screen.getByLabelText("Reason"), "Confirming SMTP wiring after config change");
}

describe("NotificationTestCentrePage", () => {
  it("lets an admin pick a template, search for a user and select them as recipient", async () => {
    const user = userEvent.setup();
    mockRoutes();
    render(<NotificationTestCentrePage />);
    await waitFor(() => expect(screen.getByLabelText("Template")).toBeInTheDocument());

    await fillOutForm(user);
    expect(screen.getByLabelText("Recipient")).toHaveValue("user-1");
  });

  it("derives the channel from the selected template rather than letting it be chosen freely", async () => {
    const user = userEvent.setup();
    mockRoutes();
    render(<NotificationTestCentrePage />);
    await waitFor(() => expect(screen.getByLabelText("Template")).toBeInTheDocument());

    await user.selectOptions(screen.getByLabelText("Template"), "email_verification");
    expect(screen.getByText(/Channel: Email/)).toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText("Template"), "calendar.event.reminder");
    expect(screen.getByText(/Channel: In App/)).toBeInTheDocument();
  });

  it("sends exactly the template type, recipient, reason and confirmed flag to the test-send endpoint", async () => {
    const user = userEvent.setup();
    mockRoutes();
    post.mockResolvedValue(undefined);
    render(<NotificationTestCentrePage />);
    await waitFor(() => expect(screen.getByLabelText("Template")).toBeInTheDocument());

    await fillOutForm(user);
    await user.click(screen.getByRole("button", { name: "Send test notification" }));

    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/notification-templates/email_verification/test-send", {
        recipient_user_id: "user-1",
        reason: "Confirming SMTP wiring after config change",
        confirmed: true,
      }),
    );
  });

  it("shows a success state after a test send", async () => {
    const user = userEvent.setup();
    mockRoutes();
    post.mockResolvedValue(undefined);
    render(<NotificationTestCentrePage />);
    await waitFor(() => expect(screen.getByLabelText("Template")).toBeInTheDocument());
    await fillOutForm(user);
    await user.click(screen.getByRole("button", { name: "Send test notification" }));
    expect(await screen.findByText("Test notification sent.")).toBeInTheDocument();
  });

  it("shows a failure state when the test-send request fails, without a false success message", async () => {
    const user = userEvent.setup();
    mockRoutes();
    post.mockRejectedValue(new Error("SMTP relay refused the connection"));
    render(<NotificationTestCentrePage />);
    await waitFor(() => expect(screen.getByLabelText("Template")).toBeInTheDocument());
    await fillOutForm(user);
    await user.click(screen.getByRole("button", { name: "Send test notification" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("SMTP relay refused the connection");
    expect(screen.queryByText("Test notification sent.")).not.toBeInTheDocument();
  });

  it("never claims that testing a security notification performs a genuine security action", async () => {
    mockRoutes();
    render(<NotificationTestCentrePage />);
    await waitFor(() => expect(screen.getByLabelText("Template")).toBeInTheDocument());
    expect(
      screen.getByText(/never performs a real security action/i, { exact: false }),
    ).toBeInTheDocument();
    const bodyText = document.body.textContent ?? "";
    expect(bodyText.toLowerCase()).not.toMatch(/will reset (the |your )?password/);
    // Let PlatformShell's own /auth/me resolution settle before the test ends.
    await waitFor(() => expect(screen.getByText(actor.display_name)).toBeInTheDocument());
  });

  it("disables the send button until a template and recipient are both chosen", async () => {
    mockRoutes();
    render(<NotificationTestCentrePage />);
    await waitFor(() => expect(screen.getByLabelText("Template")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Send test notification" })).toBeDisabled();
    // Let PlatformShell's own /auth/me resolution settle before the test ends.
    await waitFor(() => expect(screen.getByText(actor.display_name)).toBeInTheDocument());
  });
});
