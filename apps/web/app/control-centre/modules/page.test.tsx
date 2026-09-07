import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ModulesPage from "./page";

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

const modules = [
  {
    key: "calendar",
    name: "Calendar",
    description: "Household calendar module.",
    category: "core",
    dependencies: [],
    enabled: true,
    release_state: "released",
  },
];

beforeEach(() => {
  vi.clearAllMocks();
  get.mockResolvedValue(modules);
  put.mockResolvedValue({});
  post.mockResolvedValue({});
});

describe("Modules & Features", () => {
  it("renders module lifecycle state with badges", async () => {
    render(<ModulesPage />);
    expect(await screen.findByText("Calendar")).toBeInTheDocument();
    expect(screen.getByText("Enabled")).toBeInTheDocument();
    expect(screen.getAllByText("Released").length).toBeGreaterThan(0);
  });

  it("keeps Apply change disabled until the draft differs from committed state and a reason is entered", async () => {
    render(<ModulesPage />);
    await screen.findByText("Calendar");
    const applyButton = screen.getByRole("button", { name: "Apply change" });
    expect(applyButton).toBeDisabled();

    const select = screen.getByRole("combobox");
    await userEvent.selectOptions(select, "beta");
    // Still disabled: reason not yet provided.
    expect(applyButton).toBeDisabled();

    const reasonInput = screen.getAllByRole("textbox")[0];
    await userEvent.type(reasonInput, "Rolling back to beta for testing");
    expect(applyButton).toBeEnabled();
  });

  it("re-enables Apply change as disabled once the draft reverts to the committed state", async () => {
    render(<ModulesPage />);
    await screen.findByText("Calendar");
    const select = screen.getByRole("combobox");
    const reasonInput = screen.getAllByRole("textbox")[0];
    await userEvent.type(reasonInput, "Testing dirty tracking behaviour");
    await userEvent.selectOptions(select, "beta");
    const applyButton = screen.getByRole("button", { name: "Apply change" });
    expect(applyButton).toBeEnabled();
    await userEvent.selectOptions(select, "released");
    expect(applyButton).toBeDisabled();
  });

  it("confirms via dialog and sends the exact draft/reason payload with confirmed:true", async () => {
    render(<ModulesPage />);
    await screen.findByText("Calendar");
    const select = screen.getByRole("combobox");
    await userEvent.selectOptions(select, "beta");
    const reasonInput = screen.getAllByRole("textbox")[0];
    await userEvent.type(reasonInput, "Rolling back to beta for testing");
    await userEvent.click(screen.getByRole("button", { name: "Apply change" }));

    const dialog = await screen.findByRole("dialog", { name: /Apply lifecycle change/i });
    expect(within(dialog).getByText("Apply the lifecycle change to Calendar?")).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Apply change" }));

    await waitFor(() =>
      expect(put).toHaveBeenCalledWith("/modules/calendar", {
        enabled: true,
        release_state: "beta",
        reason: "Rolling back to beta for testing",
        confirmed: true,
      }),
    );
  });

  it("opens the reauth modal on a 403 and retries the same save once verified", async () => {
    put.mockImplementation(() => {
      const priorAttempts = put.mock.calls.length;
      if (priorAttempts === 1) return Promise.reject(new ApiError(403, "Recent authentication required."));
      return Promise.resolve({});
    });
    render(<ModulesPage />);
    await screen.findByText("Calendar");
    await userEvent.selectOptions(screen.getByRole("combobox"), "beta");
    await userEvent.type(screen.getAllByRole("textbox")[0], "Rolling back to beta for testing");
    await userEvent.click(screen.getByRole("button", { name: "Apply change" }));
    const dialog = await screen.findByRole("dialog", { name: /Apply lifecycle change/i });
    await userEvent.click(within(dialog).getByRole("button", { name: "Apply change" }));

    const reauthDialog = await screen.findByRole("dialog", { name: /Confirm it.s you/i });
    await userEvent.type(within(reauthDialog).getByLabelText("Password"), "hunter2");
    await userEvent.click(within(reauthDialog).getByRole("button", { name: "Confirm" }));

    await waitFor(() => expect(put).toHaveBeenCalledTimes(2));
    expect(post).toHaveBeenCalledWith("/auth/reauthenticate", { password: "hunter2" });
  });
});
