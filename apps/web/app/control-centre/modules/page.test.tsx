import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ModulesPage from "./page";

// Coverage for the Modules & Features desktop table redesign — see the PCC
// visual/UX QA task this replaces the old one-giant-card-per-module layout
// for. No FeatureFlag semantics, module precedence, entitlement rules,
// lifecycle rules, audit/recent-auth/confirmation requirements or backend
// endpoints changed — this is presentation only, same PUT /modules/{key}
// payload shape as before.

vi.mock("next/navigation", () => ({
  usePathname: () => "/control-centre/modules",
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
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
const put = platformApi.put as unknown as ReturnType<typeof vi.fn>;
const post = platformApi.post as unknown as ReturnType<typeof vi.fn>;

// The real shape GET /modules returns (see mykhaya.module_registry.feature_modules
// and routers.platform.modules) — every FeatureKey-backed released/beta module,
// Tasks/Plans already excluded server-side as hidden.
const modules = [
  {
    key: "calendar",
    name: "Calendar",
    description: "Shared household events, appointments and schedules.",
    category: "Family",
    dependencies: ["household_members"],
    enabled: true,
    release_state: "released",
  },
  {
    key: "shopping",
    name: "Lists",
    description: "Shared household lists.",
    category: "Family",
    dependencies: ["household_members"],
    enabled: true,
    release_state: "released",
  },
  {
    key: "meals",
    name: "Meal Plans",
    description: "Plan meals together.",
    category: "Family",
    dependencies: ["household_members"],
    enabled: true,
    release_state: "released",
  },
  {
    key: "wish_lists",
    name: "Wishlists",
    description: "Gift ideas for birthdays and Christmas.",
    category: "Family",
    dependencies: ["household_members"],
    enabled: true,
    release_state: "released",
  },
  {
    key: "nudges",
    name: "Nudges",
    description: "Routines, reminders and things to do.",
    category: "Family",
    dependencies: ["household_members"],
    enabled: true,
    release_state: "released",
  },
  {
    key: "notifications",
    name: "Notifications",
    description: "Push, email and in-app reminders.",
    category: "Communication",
    dependencies: [],
    enabled: true,
    release_state: "released",
  },
  {
    key: "external_sharing",
    name: "External sharing",
    description: "Share a calendar with people outside the Home.",
    category: "Experimental",
    dependencies: ["household_members", "calendar"],
    enabled: false,
    release_state: "beta",
  },
];

beforeEach(() => {
  vi.clearAllMocks();
  get.mockResolvedValue(modules);
  put.mockResolvedValue({});
  post.mockResolvedValue({});
});

function rowFor(name: string) {
  // The module name is uniquely rendered inside a <strong> (the Module
  // column's primary value) — safer than matching on cell accessible name,
  // which can collide with other cells' text (e.g. "Calendar capability").
  return screen.getByText(name, { selector: "strong" }).closest("tr") as HTMLElement;
}

describe("Modules & Features — table", () => {
  it("1. Calendar row renders", async () => {
    render(<ModulesPage />);
    expect(await screen.findByText("Calendar")).toBeInTheDocument();
  });

  it("2. Lists row renders", async () => {
    render(<ModulesPage />);
    expect(await screen.findByText("Lists")).toBeInTheDocument();
  });

  it("3. Meal Plans row renders", async () => {
    render(<ModulesPage />);
    expect(await screen.findByText("Meal Plans")).toBeInTheDocument();
  });

  it("4. Wishlists row renders", async () => {
    render(<ModulesPage />);
    expect(await screen.findByText("Wishlists")).toBeInTheDocument();
  });

  it("5. Nudges row renders", async () => {
    render(<ModulesPage />);
    expect(await screen.findByText("Nudges")).toBeInTheDocument();
  });

  it("6. Notifications renders as Infrastructure, not a Home module", async () => {
    render(<ModulesPage />);
    await screen.findByText("Notifications");
    expect(within(rowFor("Notifications")).getByText("Infrastructure")).toBeInTheDocument();
  });

  it("7. External sharing renders as Calendar capability / Beta", async () => {
    render(<ModulesPage />);
    await screen.findByText("External sharing");
    const row = rowFor("External sharing");
    expect(within(row).getByText("Calendar capability")).toBeInTheDocument();
    expect(within(row).getByText("Beta")).toBeInTheDocument();
  });

  it("8. Tasks absent from the table", async () => {
    render(<ModulesPage />);
    await screen.findByText("Calendar");
    expect(screen.queryByText("Tasks")).not.toBeInTheDocument();
  });

  it("9. Plans absent from the table", async () => {
    render(<ModulesPage />);
    await screen.findByText("Calendar");
    expect(screen.queryByText("Plans")).not.toBeInTheDocument();
  });

  it("10. Lifecycle shown correctly per row", async () => {
    render(<ModulesPage />);
    await screen.findByText("Calendar");
    expect(within(rowFor("Calendar")).getByText("Released")).toBeInTheDocument();
    expect(within(rowFor("External sharing")).getByText("Beta")).toBeInTheDocument();
  });

  it("11. Enabled/Disabled platform state shown correctly per row", async () => {
    render(<ModulesPage />);
    await screen.findByText("Calendar");
    expect(within(rowFor("Calendar")).getByText("Enabled")).toBeInTheDocument();
    expect(within(rowFor("External sharing")).getByText("Disabled")).toBeInTheDocument();
  });

  it("21. No permanent giant reason field remains on the main screen", async () => {
    render(<ModulesPage />);
    await screen.findByText("Calendar");
    expect(screen.queryByLabelText("Reason")).not.toBeInTheDocument();
    expect(screen.queryByText("Reason for lifecycle changes")).not.toBeInTheDocument();
  });
});

describe("Modules & Features — Manage dialog", () => {
  it("12. Manage opens the correct module editor", async () => {
    render(<ModulesPage />);
    await screen.findByText("Calendar");
    await userEvent.click(within(rowFor("Calendar")).getByRole("button", { name: "Manage" }));
    expect(await screen.findByRole("dialog", { name: "Manage Calendar" })).toBeInTheDocument();
  });

  it("13. Existing lifecycle value pre-populates", async () => {
    render(<ModulesPage />);
    await screen.findByText("External sharing");
    await userEvent.click(
      within(rowFor("External sharing")).getByRole("button", { name: "Manage" }),
    );
    const dialog = await screen.findByRole("dialog", { name: "Manage External sharing" });
    expect(within(dialog).getByRole("combobox")).toHaveValue("beta");
  });

  it("14. Existing platform enabled state pre-populates", async () => {
    render(<ModulesPage />);
    await screen.findByText("External sharing");
    await userEvent.click(
      within(rowFor("External sharing")).getByRole("button", { name: "Manage" }),
    );
    const dialog = await screen.findByRole("dialog", { name: "Manage External sharing" });
    // Disabled -> the toggle button offers "Enable" (it reflects current state).
    expect(within(dialog).getByRole("button", { name: "Enable" })).toBeInTheDocument();
  });

  it("16. Cancel closes the Manage dialog without mutating anything", async () => {
    render(<ModulesPage />);
    await screen.findByText("Calendar");
    await userEvent.click(within(rowFor("Calendar")).getByRole("button", { name: "Manage" }));
    const dialog = await screen.findByRole("dialog", { name: "Manage Calendar" });
    await userEvent.selectOptions(within(dialog).getByRole("combobox"), "beta");
    await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: "Manage Calendar" })).not.toBeInTheDocument(),
    );
    expect(put).not.toHaveBeenCalled();
  });

  it("Apply change is disabled until the draft differs from the committed state", async () => {
    render(<ModulesPage />);
    await screen.findByText("Calendar");
    await userEvent.click(within(rowFor("Calendar")).getByRole("button", { name: "Manage" }));
    const dialog = await screen.findByRole("dialog", { name: "Manage Calendar" });
    expect(within(dialog).getByRole("button", { name: "Apply change" })).toBeDisabled();
    await userEvent.selectOptions(within(dialog).getByRole("combobox"), "beta");
    expect(within(dialog).getByRole("button", { name: "Apply change" })).toBeEnabled();
  });
});

describe("Modules & Features — confirmation and mutation", () => {
  async function openManageAndChange(name: string) {
    await userEvent.click(within(rowFor(name)).getByRole("button", { name: "Manage" }));
    const dialog = await screen.findByRole("dialog", { name: `Manage ${name}` });
    await userEvent.selectOptions(within(dialog).getByRole("combobox"), "beta");
    await userEvent.click(within(dialog).getByRole("button", { name: "Apply change" }));
    return screen.findByRole("dialog", { name: `Apply changes to ${name}` });
  }

  it("15. Reason is required before Apply change can be submitted in the confirm step", async () => {
    render(<ModulesPage />);
    await screen.findByText("Calendar");
    const confirm = await openManageAndChange("Calendar");
    const reasonInput = within(confirm).getByLabelText(/reason for this administrative action/i);
    expect(reasonInput).toBeRequired();
    expect(reasonInput).toHaveAttribute("minlength", "10");
  });

  it("18. Confirmation flow is still required — the change summary is shown before Apply", async () => {
    render(<ModulesPage />);
    await screen.findByText("Calendar");
    const confirm = await openManageAndChange("Calendar");
    expect(within(confirm).getByText(/Lifecycle: Released → Beta/)).toBeInTheDocument();
    expect(within(confirm).getByText(/Platform state: Enabled → Enabled/)).toBeInTheDocument();
    expect(put).not.toHaveBeenCalled();
  });

  it("17. Apply uses the existing mutation endpoint with the same payload shape", async () => {
    render(<ModulesPage />);
    await screen.findByText("Calendar");
    const confirm = await openManageAndChange("Calendar");
    await userEvent.type(
      within(confirm).getByLabelText(/reason for this administrative action/i),
      "Rolling back to beta for testing",
    );
    await userEvent.click(within(confirm).getByRole("button", { name: "Apply change" }));

    await waitFor(() =>
      expect(put).toHaveBeenCalledWith("/modules/calendar", {
        enabled: true,
        release_state: "beta",
        reason: "Rolling back to beta for testing",
        confirmed: true,
      }),
    );
  });

  it("19. A successful mutation refreshes row state and closes the dialogs", async () => {
    // platformApi.get is a single shared mock — PlatformShell's own chrome
    // makes unrelated GET calls through it too, so a plain
    // mockResolvedValueOnce (keyed only on call order) can be consumed by
    // one of those instead of the /modules refresh this test cares about.
    // Keying on the requested path avoids that.
    let refreshed = false;
    get.mockImplementation((path: string) =>
      Promise.resolve(
        path === "/modules" && refreshed
          ? modules.map((module) =>
              module.key === "calendar" ? { ...module, release_state: "beta" } : module,
            )
          : modules,
      ),
    );
    render(<ModulesPage />);
    await screen.findByText("Calendar");
    const confirm = await openManageAndChange("Calendar");
    await userEvent.type(
      within(confirm).getByLabelText(/reason for this administrative action/i),
      "Rolling back to beta for testing",
    );
    refreshed = true;
    await userEvent.click(within(confirm).getByRole("button", { name: "Apply change" }));

    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: "Apply changes to Calendar" })).not.toBeInTheDocument(),
    );
    await waitFor(() => expect(within(rowFor("Calendar")).getByText("Beta")).toBeInTheDocument());
  });

  it("20. A failed mutation shows the existing PCC transient error notification", async () => {
    put.mockRejectedValue(new Error("The lifecycle change could not be saved."));
    render(<ModulesPage />);
    await screen.findByText("Calendar");
    const confirm = await openManageAndChange("Calendar");
    await userEvent.type(
      within(confirm).getByLabelText(/reason for this administrative action/i),
      "Rolling back to beta for testing",
    );
    await userEvent.click(within(confirm).getByRole("button", { name: "Apply change" }));

    expect(
      await screen.findByText("The lifecycle change could not be saved."),
    ).toBeInTheDocument();
  });

  it("opens the reauth modal on a 403 and retries the same save once verified", async () => {
    put.mockImplementation(() => {
      const priorAttempts = put.mock.calls.length;
      if (priorAttempts === 1) return Promise.reject(new ApiError(403, "Recent authentication required."));
      return Promise.resolve({});
    });
    render(<ModulesPage />);
    await screen.findByText("Calendar");
    const confirm = await openManageAndChange("Calendar");
    await userEvent.type(
      within(confirm).getByLabelText(/reason for this administrative action/i),
      "Rolling back to beta for testing",
    );
    await userEvent.click(within(confirm).getByRole("button", { name: "Apply change" }));

    const reauthDialog = await screen.findByRole("dialog", { name: /Confirm it.s you/i });
    await userEvent.type(within(reauthDialog).getByLabelText("Password"), "hunter2");
    await userEvent.click(within(reauthDialog).getByRole("button", { name: "Confirm" }));

    await waitFor(() => expect(put).toHaveBeenCalledTimes(2));
    expect(post).toHaveBeenCalledWith("/auth/reauthenticate", { password: "hunter2" });
  });
});
