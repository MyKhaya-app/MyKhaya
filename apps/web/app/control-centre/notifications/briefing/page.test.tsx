import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import DailyBriefingPage from "./page";

const stableRouter = { replace: vi.fn(), push: vi.fn() };
vi.mock("next/navigation", () => ({
  usePathname: () => "/control-centre/notifications/briefing",
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

const actor = {
  id: "op-1",
  email: "op@mykhaya.app",
  display_name: "Operator One",
  role: "platform_owner",
  mfa_enrolled: true,
  session_status: "full" as const,
};

const allTemplates = [
  {
    template_type: "briefing.title",
    module: "daily_briefing",
    channel: "in_app",
    description: "The briefing's heading.",
    allowed_variables: ["count_phrase"],
    default_subject: "You have {{count_phrase}} today.",
    default_body: "You have {{count_phrase}} today.",
    subject: "You have {{count_phrase}} today.",
    body: "You have {{count_phrase}} today.",
    is_override: false,
    enabled: true,
    disableable: true,
    security_critical: false,
    is_stale: false,
    updated_at: null,
    updated_by: null,
  },
  {
    template_type: "briefing.intro",
    module: "daily_briefing",
    channel: "in_app",
    description: "The briefing's intro line.",
    allowed_variables: [],
    default_subject: "Please take care of yourself!",
    default_body: "Please take care of yourself!",
    subject: "Have a wonderful day!",
    body: "Have a wonderful day!",
    is_override: true,
    enabled: true,
    disableable: true,
    security_critical: false,
    is_stale: false,
    updated_at: "2026-08-01T00:00:00Z",
    updated_by: "Operator One",
  },
  {
    template_type: "calendar.event.reminder",
    module: "calendar",
    channel: "in_app",
    description: "Not part of the briefing.",
    allowed_variables: [],
    default_subject: "x",
    default_body: "x",
    subject: "x",
    body: "x",
    is_override: false,
    enabled: true,
    disableable: true,
    security_critical: false,
    is_stale: false,
    updated_at: null,
    updated_by: null,
  },
];

function mockRoutes() {
  get.mockImplementation((path: string) => {
    if (path === "/auth/me") return Promise.resolve(actor);
    if (path === "/notification-templates") return Promise.resolve(allTemplates);
    return Promise.reject(new Error(`unexpected path ${path}`));
  });
}

beforeEach(() => {
  get.mockReset();
  put.mockReset();
  del.mockReset();
  vi.spyOn(window, "confirm").mockReturnValue(true);
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("DailyBriefingPage", () => {
  it("shows only the two briefing wording fragments, not the full registry", async () => {
    mockRoutes();
    render(<DailyBriefingPage />);
    await waitFor(() => expect(screen.getByText("Heading")).toBeInTheDocument());
    expect(screen.getByText("Intro line")).toBeInTheDocument();
    expect(screen.queryByText(/calendar\.event\.reminder/)).not.toBeInTheDocument();
  });

  it("populates the current effective wording, not the default, for a customised fragment", async () => {
    mockRoutes();
    render(<DailyBriefingPage />);
    await waitFor(() => expect(screen.getByText("Intro line")).toBeInTheDocument());
    const introSection = screen.getByText("Intro line").closest("section")!;
    const textarea = introSection.querySelector("textarea")!;
    expect(textarea).toHaveValue("Have a wonderful day!");
  });

  it("exposes the built-in default in a details panel without altering it", async () => {
    mockRoutes();
    render(<DailyBriefingPage />);
    await waitFor(() => expect(screen.getByText("Intro line")).toBeInTheDocument());
    const introSection = screen.getByText("Intro line").closest("section")!;
    expect(introSection).toHaveTextContent("Please take care of yourself!");
    expect(introSection).toHaveTextContent("Have a wonderful day!");
  });

  it("sends the correct payload when saving a briefing fragment", async () => {
    const user = userEvent.setup();
    mockRoutes();
    put.mockResolvedValue(allTemplates[0]);
    render(<DailyBriefingPage />);
    await waitFor(() => expect(screen.getByText("Heading")).toBeInTheDocument());

    const headingSection = screen.getByText("Heading").closest("section")!;
    const reasonInput = headingSection.querySelector("input[name=reason]")!;
    await user.type(reasonInput, "Warmer tone for the morning heading");
    await user.click(within(headingSection).getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(put).toHaveBeenCalledWith("/notification-templates/briefing.title", {
        subject: "You have {{count_phrase}} today.",
        body: "You have {{count_phrase}} today.",
        enabled: true,
        reason: "Warmer tone for the morning heading",
        confirmed: true,
      }),
    );
  });

  it("only offers reset for the fragment that is actually customised", async () => {
    mockRoutes();
    render(<DailyBriefingPage />);
    await waitFor(() => expect(screen.getByText("Heading")).toBeInTheDocument());

    const headingSection = screen.getByText("Heading").closest("section")!;
    const introSection = screen.getByText("Intro line").closest("section")!;
    expect(within(headingSection).queryByRole("button", { name: "Reset to default" })).not.toBeInTheDocument();
    expect(within(introSection).getByRole("button", { name: "Reset to default" })).toBeInTheDocument();
  });

  it("resets a fragment back to default after confirmation", async () => {
    const user = userEvent.setup();
    mockRoutes();
    del.mockResolvedValue(undefined);
    render(<DailyBriefingPage />);
    await waitFor(() => expect(screen.getByText("Intro line")).toBeInTheDocument());

    const introSection = screen.getByText("Intro line").closest("section")!;
    await user.click(within(introSection).getByRole("button", { name: "Reset to default" }));

    expect(window.confirm).toHaveBeenCalled();
    await waitFor(() => expect(del).toHaveBeenCalledWith("/notification-templates/briefing.intro"));
    expect(await screen.findByText(/Reset "briefing.intro" to its default/)).toBeInTheDocument();
  });
});
