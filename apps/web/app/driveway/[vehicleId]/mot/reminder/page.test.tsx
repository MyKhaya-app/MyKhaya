import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import NewMotReminderPage from "./page";

// New MOT reminder (Screen 4): pre-filled from the MOT, owner-only
// recipient, nudge timing chips, yearly repeat switch, saved summary.

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  usePathname: () => "/driveway/v1/mot/reminder",
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

vi.mock("@/components/auth-provider", () => ({
  useAuth: () => ({ user: { id: "u1", display_name: "Anthony Hales" } }),
}));

vi.mock("@mykhaya/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@mykhaya/api-client")>();
  return {
    ...actual,
    api: { ...actual.api, vehicle: vi.fn(), members: vi.fn(), vehicleMot: vi.fn(), vehicleMotNudges: vi.fn(), saveVehicleMotNudges: vi.fn() },
  };
});

const { ApiError, api } = await import("@mykhaya/api-client");

function resolvedParams(vehicleId: string): Promise<{ vehicleId: string }> {
  const promise = Promise.resolve({ vehicleId }) as Promise<{ vehicleId: string }> & { status?: string; value?: { vehicleId: string } };
  promise.status = "fulfilled";
  promise.value = { vehicleId };
  return promise;
}

const VEHICLE = { id: "v1", owner_user_id: "u1", nickname: "Family car", make: "BMW", model: "i4", country_code: "GB", registration: "AP22OOJ" };

function renderPage() {
  return render(<NewMotReminderPage params={resolvedParams("v1")} />);
}

beforeEach(() => {
  vi.clearAllMocks();
  window.history.replaceState(null, "", "/driveway/v1/mot/reminder?from=history");
  (api.vehicle as ReturnType<typeof vi.fn>).mockResolvedValue(VEHICLE);
  (api.members as ReturnType<typeof vi.fn>).mockResolvedValue([
    { user_id: "u1", display_name: "Anthony Hales" },
    { user_id: "u2", display_name: "Megan Hales" },
  ]);
  (api.vehicleMot as ReturnType<typeof vi.fn>).mockResolvedValue({ eligible: true, summary: { due_date: "2027-08-25" }, tests: [] });
  (api.vehicleMotNudges as ReturnType<typeof vi.fn>).mockResolvedValue({ plan: null });
});

describe("New MOT reminder", () => {
  it("is pre-filled from the MOT record and goes back where it came from", async () => {
    renderPage();
    expect(await screen.findByLabelText("Reminder")).toHaveValue("Book MOT – BMW i4");
    expect(screen.getByLabelText("MOT expires")).toHaveValue("2027-08-25");
    expect(screen.getByText("Filled in from your MOT record. Check it over and save.")).toBeInTheDocument();
    expect(screen.getByText("AP22 OOJ")).toHaveClass("drv-plate");
    expect(screen.getByRole("link", { name: "BMW i4" })).toHaveAttribute("href", "/driveway/v1/mot");
    const when = screen.getByRole("group", { name: "Nudge me" });
    const pressed = within(when)
      .getAllByRole("button")
      .filter((chip) => chip.getAttribute("aria-pressed") === "true")
      .map((chip) => chip.textContent);
    expect(pressed).toEqual(["30 days before", "7 days before"]);
    expect(screen.getByRole("switch", { name: "Repeat every year" })).toHaveAttribute("aria-checked", "true");
  });

  it("only ever sends MOT nudges to the vehicle's owner", async () => {
    renderPage();
    const who = await screen.findByRole("group", { name: "Who should get it?" });
    expect(within(who).getAllByRole("button").map((chip) => chip.textContent)).toEqual(["Me"]);
    expect(screen.queryByRole("button", { name: "Megan" })).not.toBeInTheDocument();
  });

  it("saves the plan and shows who will be nudged and when", async () => {
    (api.saveVehicleMotNudges as ReturnType<typeof vi.fn>).mockResolvedValue({
      plan: { title: "Book MOT – BMW i4", due_date: "2027-08-25", offsets: [30, 14], repeat: true, scheduled: ["2027-07-26", "2027-08-11"] },
    });
    renderPage();
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "14 days before" }));
    await user.click(screen.getByRole("button", { name: "7 days before" }));
    await user.click(screen.getByRole("button", { name: "Save nudge" }));
    await waitFor(() =>
      expect(api.saveVehicleMotNudges).toHaveBeenCalledWith("home-1", "v1", {
        title: "Book MOT – BMW i4",
        due_date: "2027-08-25",
        offsets: [30, 14],
        repeat: true,
      }),
    );
    expect(await screen.findByRole("heading", { name: "Nudge saved" })).toBeInTheDocument();
    expect(screen.getByText("We'll nudge you on 26 Jul 2027 and 11 Aug 2027. It repeats each year after the next pass.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to BMW i4" })).toHaveAttribute("href", "/driveway/v1");
    await user.click(screen.getByRole("button", { name: "Edit nudge" }));
    expect(screen.getByLabelText("Reminder")).toBeInTheDocument();
  });

  it("drops the repeat sentence when repeat is off, and needs at least one time", async () => {
    (api.saveVehicleMotNudges as ReturnType<typeof vi.fn>).mockResolvedValue({
      plan: { title: "x", due_date: "2027-08-25", offsets: [0], repeat: false, scheduled: ["2027-08-25"] },
    });
    renderPage();
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "30 days before" }));
    await user.click(screen.getByRole("button", { name: "7 days before" }));
    await user.click(screen.getByRole("button", { name: "Save nudge" }));
    expect(screen.getByText("Choose at least one time to be nudged.")).toBeInTheDocument();
    expect(api.saveVehicleMotNudges).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "On the day" }));
    await user.click(screen.getByRole("switch", { name: "Repeat every year" }));
    await user.click(screen.getByRole("button", { name: "Save nudge" }));
    expect(await screen.findByText("We'll nudge you on 25 Aug 2027.")).toBeInTheDocument();
  });

  it("re-opens an existing plan as it was saved", async () => {
    (api.vehicleMotNudges as ReturnType<typeof vi.fn>).mockResolvedValue({
      plan: { title: "MOT time", due_date: "2027-09-01", offsets: [14], repeat: false, scheduled: ["2027-08-18"] },
    });
    renderPage();
    expect(await screen.findByLabelText("Reminder")).toHaveValue("MOT time");
    expect(screen.getByLabelText("MOT expires")).toHaveValue("2027-09-01");
    expect(screen.getByRole("button", { name: "14 days before" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "30 days before" })).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByRole("switch", { name: "Repeat every year" })).toHaveAttribute("aria-checked", "false");
  });

  it("explains when the viewer can't set reminders for this vehicle", async () => {
    (api.vehicleMotNudges as ReturnType<typeof vi.fn>).mockRejectedValue(new ApiError(404, "Not found"));
    renderPage();
    expect(await screen.findByText(/Only the person this vehicle belongs to/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Save nudge" })).not.toBeInTheDocument();
  });
});
