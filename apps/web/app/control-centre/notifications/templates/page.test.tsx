import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import NotificationTemplatesPage from "./page";

const stableRouter = { replace: vi.fn(), push: vi.fn() };
vi.mock("next/navigation", () => ({
  usePathname: () => "/control-centre/notifications/templates",
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
const put = platformApi.put as unknown as ReturnType<typeof vi.fn>;
const del = platformApi.delete as unknown as ReturnType<typeof vi.fn>;
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
  {
    template_type: "calendar.event.reminder",
    module: "calendar",
    channel: "in_app",
    description: "Sent shortly before an event starts.",
    allowed_variables: ["event_title", "event_when", "event_location"],
    default_subject: "{{event_title}}",
    default_body: "{{event_title}} starts {{event_when}}{{event_location}}.",
    subject: "{{event_title}}",
    body: "{{event_title}} starts {{event_when}}{{event_location}}.",
    is_override: false,
    enabled: true,
    disableable: true,
    security_critical: false,
    is_stale: false,
    updated_at: null,
    updated_by: null,
  },
  {
    template_type: "email_verification",
    module: "security",
    channel: "email",
    description: "Verifies a new account's email address.",
    allowed_variables: ["code"],
    default_subject: "Verify your email",
    default_body: "Your verification code is {{code}}.",
    subject: "Verify your email — customised",
    body: "Your code: {{code}}.",
    is_override: true,
    enabled: true,
    disableable: false,
    security_critical: true,
    is_stale: false,
    updated_at: "2026-08-01T00:00:00Z",
    updated_by: "Operator One",
  },
];

function mockRoutes(overrides: Record<string, unknown> = {}) {
  get.mockImplementation((path: string) => {
    if (path === "/auth/me") return Promise.resolve(actor);
    if (path === "/notification-templates") return Promise.resolve(overrides.templates ?? templates);
    return Promise.reject(new Error(`unexpected path ${path}`));
  });
}

beforeEach(() => {
  get.mockReset();
  put.mockReset();
  del.mockReset();
  post.mockReset();
  vi.spyOn(window, "confirm").mockReturnValue(true);
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("NotificationTemplatesPage — list and filtering", () => {
  it("renders every registered template", async () => {
    mockRoutes();
    render(<NotificationTemplatesPage />);
    await waitFor(() => expect(screen.getByText("calendar.event.reminder")).toBeInTheDocument());
    expect(screen.getByText("email_verification")).toBeInTheDocument();
  });

  it("filters by search text across key, module and wording", async () => {
    const user = userEvent.setup();
    mockRoutes();
    render(<NotificationTemplatesPage />);
    await waitFor(() => expect(screen.getByText("calendar.event.reminder")).toBeInTheDocument());

    await user.type(screen.getByLabelText("Search"), "verifies a new account");
    expect(screen.queryByText("calendar.event.reminder")).not.toBeInTheDocument();
    expect(screen.getByText("email_verification")).toBeInTheDocument();
  });

  it("filters by module", async () => {
    const user = userEvent.setup();
    mockRoutes();
    render(<NotificationTemplatesPage />);
    await waitFor(() => expect(screen.getByText("calendar.event.reminder")).toBeInTheDocument());

    await user.selectOptions(screen.getByLabelText("Module"), "security");
    expect(screen.queryByText("calendar.event.reminder")).not.toBeInTheDocument();
    expect(screen.getByText("email_verification")).toBeInTheDocument();
  });

  it("filters by channel", async () => {
    const user = userEvent.setup();
    mockRoutes();
    render(<NotificationTemplatesPage />);
    await waitFor(() => expect(screen.getByText("calendar.event.reminder")).toBeInTheDocument());

    await user.selectOptions(screen.getByLabelText("Channel"), "email");
    expect(screen.queryByText("calendar.event.reminder")).not.toBeInTheDocument();
    expect(screen.getByText("email_verification")).toBeInTheDocument();
  });

  it("filters by enabled/disabled status", async () => {
    const user = userEvent.setup();
    mockRoutes({
      templates: [...templates, { ...templates[0], template_type: "routine.due", enabled: false }],
    });
    render(<NotificationTemplatesPage />);
    await waitFor(() => expect(screen.getByText("routine.due")).toBeInTheDocument());

    await user.selectOptions(screen.getByLabelText("Status"), "disabled");
    expect(screen.getByText("routine.due")).toBeInTheDocument();
    expect(screen.queryByText("calendar.event.reminder")).not.toBeInTheDocument();
  });

  it("filters by customised vs default origin", async () => {
    const user = userEvent.setup();
    mockRoutes();
    render(<NotificationTemplatesPage />);
    await waitFor(() => expect(screen.getByText("calendar.event.reminder")).toBeInTheDocument());

    await user.selectOptions(screen.getByLabelText("Origin"), "customised");
    expect(screen.queryByText("calendar.event.reminder")).not.toBeInTheDocument();
    expect(screen.getByText("email_verification")).toBeInTheDocument();
  });

  it("filters by security/system-critical", async () => {
    const user = userEvent.setup();
    mockRoutes();
    render(<NotificationTemplatesPage />);
    await waitFor(() => expect(screen.getByText("calendar.event.reminder")).toBeInTheDocument());

    await user.click(screen.getByLabelText(/security\/system-critical only/i));
    expect(screen.queryByText("calendar.event.reminder")).not.toBeInTheDocument();
    expect(screen.getByText("email_verification")).toBeInTheDocument();
  });

  it("shows Default/Customised and Required badges correctly", async () => {
    mockRoutes();
    render(<NotificationTemplatesPage />);
    await waitFor(() => expect(screen.getByText("calendar.event.reminder")).toBeInTheDocument());

    const defaultRow = screen.getByText("calendar.event.reminder").closest("tr")!;
    expect(within(defaultRow).getByText("Default")).toBeInTheDocument();
    expect(within(defaultRow).getByText("Enabled")).toBeInTheDocument();
    expect(within(defaultRow).queryByText("Required")).not.toBeInTheDocument();

    const protectedRow = screen.getByText("email_verification").closest("tr")!;
    expect(within(protectedRow).getByText("Customised")).toBeInTheDocument();
    expect(within(protectedRow).getByText("Required")).toBeInTheDocument();
  });
});

describe("NotificationTemplatesPage — editor", () => {
  it("populates the editor with the selected template's current values", async () => {
    const user = userEvent.setup();
    mockRoutes();
    render(<NotificationTemplatesPage />);
    await waitFor(() => expect(screen.getByText("calendar.event.reminder")).toBeInTheDocument());

    await user.click(screen.getByText("calendar.event.reminder"));
    expect(screen.getByLabelText("Subject")).toHaveValue("{{event_title}}");
    expect(screen.getByLabelText("Body")).toHaveValue(
      "{{event_title}} starts {{event_when}}{{event_location}}.",
    );
    expect(screen.getByLabelText("Enabled")).toBeChecked();
    expect(screen.getByLabelText("Enabled")).not.toBeDisabled();
  });

  it("shows allowed variables and inserts them into the body on click", async () => {
    const user = userEvent.setup();
    mockRoutes();
    render(<NotificationTemplatesPage />);
    await waitFor(() => expect(screen.getByText("calendar.event.reminder")).toBeInTheDocument());
    await user.click(screen.getByText("calendar.event.reminder"));

    const insertButton = screen.getByRole("button", { name: "Insert {{event_location}}" });
    await user.click(insertButton);
    expect(screen.getByLabelText("Body")).toHaveValue(
      "{{event_title}} starts {{event_when}}{{event_location}}.{{event_location}}",
    );
  });

  it("sends exactly subject, body, enabled, reason and confirmed on save", async () => {
    const user = userEvent.setup();
    mockRoutes();
    put.mockResolvedValue(templates[0]);
    render(<NotificationTemplatesPage />);
    await waitFor(() => expect(screen.getByText("calendar.event.reminder")).toBeInTheDocument());
    await user.click(screen.getByText("calendar.event.reminder"));

    await user.clear(screen.getByLabelText("Subject"));
    await user.type(screen.getByLabelText("Subject"), "New subject");
    await user.type(screen.getByLabelText("Reason for change"), "Clarifying the wording for users");
    await user.click(screen.getByRole("button", { name: "Save override" }));

    await waitFor(() => expect(put).toHaveBeenCalled());
    expect(put).toHaveBeenCalledWith("/notification-templates/calendar.event.reminder", {
      subject: "New subject",
      body: "{{event_title}} starts {{event_when}}{{event_location}}.",
      enabled: true,
      reason: "Clarifying the wording for users",
      confirmed: true,
    });
  });

  it("refreshes the template list after a successful save", async () => {
    const user = userEvent.setup();
    mockRoutes();
    put.mockResolvedValue(templates[0]);
    render(<NotificationTemplatesPage />);
    await waitFor(() => expect(screen.getByText("calendar.event.reminder")).toBeInTheDocument());
    await user.click(screen.getByText("calendar.event.reminder"));
    await user.type(screen.getByLabelText("Reason for change"), "Reworded for clarity today");

    get.mockClear();
    await user.click(screen.getByRole("button", { name: "Save override" }));
    await waitFor(() => expect(screen.getByText("Template saved.")).toBeInTheDocument());
    expect(get).toHaveBeenCalledWith("/notification-templates");
  });

  it("surfaces a validation error returned by the backend without saving silently", async () => {
    const user = userEvent.setup();
    mockRoutes();
    put.mockRejectedValue(new Error("Unsupported placeholder {{oops}}."));
    render(<NotificationTemplatesPage />);
    await waitFor(() => expect(screen.getByText("calendar.event.reminder")).toBeInTheDocument());
    await user.click(screen.getByText("calendar.event.reminder"));
    await user.type(screen.getByLabelText("Reason for change"), "Testing invalid placeholder");

    await user.click(screen.getByRole("button", { name: "Save override" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Unsupported placeholder");
  });

  it("renders a preview reflecting the current draft, not the saved value", async () => {
    const user = userEvent.setup();
    mockRoutes();
    post.mockResolvedValue({ subject: "School Trip", body: "School Trip starts Friday at 09:00." });
    render(<NotificationTemplatesPage />);
    await waitFor(() => expect(screen.getByText("calendar.event.reminder")).toBeInTheDocument());
    await user.click(screen.getByText("calendar.event.reminder"));

    fireEvent.change(screen.getByLabelText("Body"), { target: { value: "Draft body {{event_title}}" } });
    await user.click(screen.getByRole("button", { name: "Preview" }));

    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/notification-templates/calendar.event.reminder/preview", {
        subject: "{{event_title}}",
        body: "Draft body {{event_title}}",
      }),
    );
    expect(await screen.findByText("School Trip starts Friday at 09:00.")).toBeInTheDocument();
  });
});

describe("NotificationTemplatesPage — protected templates", () => {
  it("disables the Enabled checkbox for a non-disableable template and does not misrepresent it as toggleable", async () => {
    const user = userEvent.setup();
    mockRoutes();
    render(<NotificationTemplatesPage />);
    await waitFor(() => expect(screen.getByText("email_verification")).toBeInTheDocument());
    await user.click(screen.getAllByText("email_verification")[0]!);

    const checkbox = screen.getByLabelText(/Enabled/);
    expect(checkbox).toBeDisabled();
    expect(checkbox).toBeChecked();
    expect(screen.getByText(/cannot be disabled from Control Centre/i)).toBeInTheDocument();
  });

  it("handles a backend refusal safely if a disable is attempted anyway", async () => {
    const user = userEvent.setup();
    mockRoutes();
    put.mockRejectedValue(new Error("This notification is required and cannot be disabled."));
    render(<NotificationTemplatesPage />);
    await waitFor(() => expect(screen.getByText("email_verification")).toBeInTheDocument());
    await user.click(screen.getAllByText("email_verification")[0]!);
    await user.type(screen.getByLabelText("Reason for change"), "Attempting to disable anyway");

    await user.click(screen.getByRole("button", { name: "Save override" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("cannot be disabled");
    // The list is not corrupted by the failed attempt — still shown as enabled.
    const row = screen.getAllByText("email_verification")[0]!.closest("tr")!;
    expect(within(row).getByText("Enabled")).toBeInTheDocument();
  });
});

describe("NotificationTemplatesPage — reset behaviour", () => {
  it("resets a single customised template back to its default after confirmation", async () => {
    const user = userEvent.setup();
    mockRoutes();
    del.mockResolvedValue(undefined);
    render(<NotificationTemplatesPage />);
    await waitFor(() => expect(screen.getByText("email_verification")).toBeInTheDocument());
    await user.click(screen.getAllByText("email_verification")[0]!);

    await user.click(screen.getByRole("button", { name: "Reset to default" }));
    expect(window.confirm).toHaveBeenCalled();
    await waitFor(() => expect(del).toHaveBeenCalledWith("/notification-templates/email_verification"));
    expect(await screen.findByText("Reset to the built-in default.")).toBeInTheDocument();
    expect(screen.getByLabelText("Subject")).toHaveValue("Verify your email");
    expect(screen.getByLabelText(/Enabled/)).toBeChecked();
  });

  it("does not call delete when the reset confirmation is declined", async () => {
    const user = userEvent.setup();
    vi.spyOn(window, "confirm").mockReturnValue(false);
    mockRoutes();
    render(<NotificationTemplatesPage />);
    await waitFor(() => expect(screen.getByText("email_verification")).toBeInTheDocument());
    await user.click(screen.getAllByText("email_verification")[0]!);

    await user.click(screen.getByRole("button", { name: "Reset to default" }));
    expect(del).not.toHaveBeenCalled();
  });

  it("does not offer a reset button for a template already at its default", async () => {
    const user = userEvent.setup();
    mockRoutes();
    render(<NotificationTemplatesPage />);
    await waitFor(() => expect(screen.getByText("calendar.event.reminder")).toBeInTheDocument());
    await user.click(screen.getByText("calendar.event.reminder"));
    expect(screen.queryByRole("button", { name: "Reset to default" })).not.toBeInTheDocument();
  });

  it("requires an explicit second confirmation before restoring all templates", async () => {
    const user = userEvent.setup();
    vi.spyOn(window, "confirm").mockReturnValue(false);
    mockRoutes();
    render(<NotificationTemplatesPage />);
    await waitFor(() => expect(screen.getByText("calendar.event.reminder")).toBeInTheDocument());

    await user.click(screen.getByRole("button", { name: "Restore all templates to defaults" }));
    await user.type(screen.getByLabelText("Reason"), "Undo a bad bulk customisation");
    await user.click(screen.getByRole("button", { name: /Confirm — restore all defaults/ }));

    expect(window.confirm).toHaveBeenCalled();
    expect(post).not.toHaveBeenCalled();
  });

  it("restores all templates to defaults once confirmed, with a reason", async () => {
    const user = userEvent.setup();
    mockRoutes();
    post.mockResolvedValue(undefined);
    render(<NotificationTemplatesPage />);
    await waitFor(() => expect(screen.getByText("calendar.event.reminder")).toBeInTheDocument());

    await user.click(screen.getByRole("button", { name: "Restore all templates to defaults" }));
    await user.type(screen.getByLabelText("Reason"), "Undo a bad bulk customisation");
    await user.click(screen.getByRole("button", { name: /Confirm — restore all defaults/ }));

    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/notification-templates/reset-all", {
        reason: "Undo a bad bulk customisation",
        confirmed: true,
      }),
    );
    expect(await screen.findByText(/restored to their built-in defaults/)).toBeInTheDocument();
  });
});
