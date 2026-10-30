import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import VehicleRemindersPage from "./page";

// Coverage for Driveway's vehicle Reminders page (Phase 4). Every reminder
// shown here is an ordinary Nudges Reminder — this suite only checks
// Driveway's own listing/creation/removal wiring, not Nudges' own card
// rendering (covered separately by settings/routines-reminders tests).

const push = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push }),
  usePathname: () => "/driveway/v1/reminders",
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
      vehicle: vi.fn(),
      vehicleReminders: vi.fn(),
      createVehicleReminder: vi.fn(),
      deleteReminder: vi.fn(),
    },
  };
});

const { ApiError, api } = await import("@mykhaya/api-client");

const VEHICLE = {
  id: "v1",
  group_id: "home-1",
  owner_user_id: "u1",
  scope: "household",
  nickname: "BMW i4",
  make: "BMW",
  model: "i4",
  colour: "Black",
  year: 2022,
  fuel_type: "Electric",
  engine_size: null,
  country_code: "GB",
  registration: "AP22 OOJ",
  first_registration_date: null,
  vin: null,
  archived: false,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

const REMINDER = {
  id: "r1",
  title: "BMW i4 MOT due",
  description: null,
  scope: "household",
  owner_user_id: null,
  due_date: "2026-10-01",
  due_time: "09:00:00",
  repeat: "never",
  cadence: "once",
  category: { id: "cat-1", name: "Vehicles", created_by: "u1", created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z" },
  enabled: true,
  member_ids: [],
  next_occurrence_date: "2026-10-01",
  completed_today: false,
  created_by: "u1",
  updated_at: "2026-01-01T00:00:00Z",
};

function resolvedParams(vehicleId: string): Promise<{ vehicleId: string }> {
  const promise = Promise.resolve({ vehicleId }) as Promise<{ vehicleId: string }> & {
    status?: string;
    value?: { vehicleId: string };
  };
  promise.status = "fulfilled";
  promise.value = { vehicleId };
  return promise;
}

function renderPage(vehicleId = "v1") {
  return render(<VehicleRemindersPage params={resolvedParams(vehicleId)} />);
}

beforeEach(() => {
  vi.clearAllMocks();
  (api.vehicle as ReturnType<typeof vi.fn>).mockResolvedValue(VEHICLE);
  window.confirm = vi.fn(() => true);
});

describe("Vehicle Reminders — empty state", () => {
  it("shows the empty state and an Add reminder action when there are no linked reminders", async () => {
    (api.vehicleReminders as ReturnType<typeof vi.fn>).mockResolvedValue({ items: [] });
    renderPage();
    expect(await screen.findByText("No reminders yet")).toBeInTheDocument();
    expect(
      screen.getByText(
        "Add a reminder for anything you want MyKhaya to keep an eye on for this vehicle.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /add reminder/i })).toBeInTheDocument();
  });
});

describe("Vehicle Reminders — linked list", () => {
  it("renders only reminders linked to this vehicle, using the existing Nudge card fields", async () => {
    (api.vehicleReminders as ReturnType<typeof vi.fn>).mockResolvedValue({ items: [REMINDER] });
    renderPage();
    expect(await screen.findByText("BMW i4 MOT due")).toBeInTheDocument();
    expect(screen.getByText(/09:00/)).toBeInTheDocument();
    expect(screen.getByText(/Household/)).toBeInTheDocument();
    expect(screen.getByText(/Vehicles/)).toBeInTheDocument();
  });
});

describe("Vehicle Reminders — add reminder", () => {
  it("creates a reminder and refreshes the list on success", async () => {
    (api.vehicleReminders as ReturnType<typeof vi.fn>)
      .mockResolvedValueOnce({ items: [] })
      .mockResolvedValueOnce({ items: [REMINDER] });
    (api.createVehicleReminder as ReturnType<typeof vi.fn>).mockResolvedValue(REMINDER);
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("No reminders yet");
    await user.click(screen.getByRole("button", { name: /add reminder/i }));
    const dialog = screen.getByRole("dialog");
    await user.type(within(dialog).getByLabelText("Title"), "BMW i4 MOT due");
    await user.type(within(dialog).getByLabelText("Due date"), "2026-10-01");
    await user.click(within(dialog).getByRole("button", { name: "Add reminder" }));

    await waitFor(() =>
      expect(api.createVehicleReminder).toHaveBeenCalledWith(
        "home-1",
        "v1",
        expect.objectContaining({ title: "BMW i4 MOT due", due_date: "2026-10-01" }),
      ),
    );
    expect(await screen.findByText("BMW i4 MOT due")).toBeInTheDocument();
  });

  it("shows a validation message and does not submit without a title or due date", async () => {
    (api.vehicleReminders as ReturnType<typeof vi.fn>).mockResolvedValue({ items: [] });
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("No reminders yet");
    await user.click(screen.getByRole("button", { name: /add reminder/i }));
    const dialog = screen.getByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Add reminder" }));
    // Each problem is shown on, and announced with, the field it concerns.
    const title = within(dialog).getByLabelText("Title");
    expect(title).toHaveAttribute("aria-invalid", "true");
    expect(title).toHaveAccessibleDescription("Add a title.");
    expect(within(dialog).getByLabelText("Due date")).toHaveAccessibleDescription("Choose a due date.");
    await waitFor(() => expect(title).toHaveFocus());
    expect(api.createVehicleReminder).not.toHaveBeenCalled();
  });
});

describe("Vehicle Reminders — remove", () => {
  it("removes a reminder and refreshes the list", async () => {
    (api.vehicleReminders as ReturnType<typeof vi.fn>)
      .mockResolvedValueOnce({ items: [REMINDER] })
      .mockResolvedValueOnce({ items: [] });
    (api.deleteReminder as ReturnType<typeof vi.fn>).mockResolvedValue(undefined);
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("BMW i4 MOT due");
    await user.click(screen.getByRole("button", { name: /remove bmw i4 mot due/i }));

    await waitFor(() => expect(api.deleteReminder).toHaveBeenCalledWith("home-1", "r1"));
    expect(await screen.findByText("No reminders yet")).toBeInTheDocument();
  });
});

describe("Vehicle Reminders — not found", () => {
  it("shows a not-found message for a vehicle that does not exist or is not accessible", async () => {
    (api.vehicle as ReturnType<typeof vi.fn>).mockRejectedValue(new ApiError(404, "Not found"));
    (api.vehicleReminders as ReturnType<typeof vi.fn>).mockRejectedValue(new ApiError(404, "Not found"));
    renderPage();
    expect(await screen.findByText("That vehicle could not be found.")).toBeInTheDocument();
  });
});

// The Add reminder sheet on the shared FormSheet (docs/design/forms.md).
describe("Vehicle Reminders — add reminder sheet", () => {
  async function openSheet() {
    (api.vehicleReminders as ReturnType<typeof vi.fn>).mockResolvedValue({ items: [] });
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("No reminders yet");
    await user.click(screen.getByRole("button", { name: /add reminder/i }));
    return { user, dialog: screen.getByRole("dialog", { name: "Add reminder" }) };
  }

  it("has a Save and Cancel footer outside the scrolling form, and pairs the date and time", async () => {
    const { dialog } = await openSheet();
    const footer = dialog.querySelector(".sheet-footer")!;
    const add = within(dialog).getByRole("button", { name: "Add reminder" });
    expect(footer).toContainElement(add);
    expect(footer).toContainElement(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(add).toHaveAttribute("form", "vehicle-reminder-form");
    expect(within(dialog).getByLabelText("Due date").closest(".form-row")).toBe(within(dialog).getByLabelText("Due time").closest(".form-row"));
  });

  it("cancels without creating a reminder", async () => {
    const { user, dialog } = await openSheet();
    await user.type(within(dialog).getByLabelText("Title"), "Tyres");
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(api.createVehicleReminder).not.toHaveBeenCalled();
  });

  it("locks every dismissal while saving, then shows a failure inside the sheet and keeps the draft", async () => {
    let reject: (cause: unknown) => void = () => {};
    (api.createVehicleReminder as ReturnType<typeof vi.fn>).mockReturnValue(new Promise((_, fail) => { reject = fail; }));
    const { user, dialog } = await openSheet();
    await user.type(within(dialog).getByLabelText("Title"), "Tyres");
    await user.type(within(dialog).getByLabelText("Due date"), "2026-11-20");
    await user.click(within(dialog).getByRole("button", { name: "Add reminder" }));

    expect(await within(dialog).findByRole("button", { name: "Adding…" })).toBeDisabled();
    expect(within(dialog).getByRole("button", { name: "Cancel" })).toBeDisabled();
    await user.keyboard("{Escape}");
    expect(screen.getByRole("dialog", { name: "Add reminder" })).toBeInTheDocument();

    reject(new ApiError(422, "Give the reminder a name."));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("Give the reminder a name.");
    expect(within(dialog).getByLabelText("Title")).toHaveValue("Tyres");
    expect(within(dialog).getByLabelText("Due date")).toHaveValue("2026-11-20");
    expect(within(dialog).getByRole("button", { name: "Add reminder" })).toBeEnabled();
    expect(within(dialog).getByRole("button", { name: "Cancel" })).toBeEnabled();
  });
});
