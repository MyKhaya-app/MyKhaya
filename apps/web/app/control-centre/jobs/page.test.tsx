import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import JobsPage from "./page";

vi.mock("next/navigation", () => ({
  usePathname: () => "/control-centre/jobs",
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
const post = platformApi.post as unknown as ReturnType<typeof vi.fn>;

const failedJob = {
  id: "j1",
  job_type: "send_reminder",
  state: "failed",
  created_at: "2026-09-07T09:00:00Z",
  started_at: "2026-09-07T09:00:05Z",
  completed_at: null,
  duration_ms: 120,
  retry_count: 1,
  safe_failure_message: "Timed out",
  occurrence_id: null,
  scheduled_for: null,
};
const response = {
  summary: { queued: 1, running: 0, failed: 1, completed: 3, scheduled: 0 },
  items: [failedJob],
  total: 1,
};

beforeEach(() => {
  vi.clearAllMocks();
  get.mockResolvedValue(response);
  post.mockResolvedValue({});
});

describe("Jobs & scheduler", () => {
  it("renders job statuses and summary counts", async () => {
    render(<JobsPage />);
    expect(await screen.findByText("Send Reminder")).toBeInTheDocument();
    expect(screen.getAllByText("Failed").length).toBeGreaterThan(0);
    expect(screen.getByText("Timed out")).toBeInTheDocument();
  });

  it("keeps Retry disabled until a reason of at least 10 characters is entered", async () => {
    render(<JobsPage />);
    await screen.findByText("Send Reminder");
    const retryButton = screen.getByRole("button", { name: "Retry" });
    expect(retryButton).toBeDisabled();
    await userEvent.type(screen.getByLabelText("Reason for retry"), "Retrying after fix");
    expect(retryButton).toBeEnabled();
  });

  it("confirms via dialog and sends the exact reason/confirmed payload", async () => {
    render(<JobsPage />);
    await screen.findByText("Send Reminder");
    await userEvent.type(screen.getByLabelText("Reason for retry"), "Retrying after fix");
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    const dialog = await screen.findByRole("dialog", { name: "Retry job" });
    expect(within(dialog).getByText("Retry Send Reminder?")).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Retry" }));
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/jobs/j1/retry", { reason: "Retrying after fix", confirmed: true }),
    );
  });

  it("surfaces a safe error message instead of a raw failure on a rejected retry", async () => {
    post.mockRejectedValueOnce(new ApiError(409, "Only failed queued jobs can be retried."));
    render(<JobsPage />);
    await screen.findByText("Send Reminder");
    await userEvent.type(screen.getByLabelText("Reason for retry"), "Retrying after fix");
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    const dialog = await screen.findByRole("dialog", { name: "Retry job" });
    await userEvent.click(within(dialog).getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("Only failed queued jobs can be retried.")).toBeInTheDocument();
  });

  it("opens the reauth modal on a 403 and retries the same retry once verified", async () => {
    post.mockImplementation((path: string) => {
      if (path === "/auth/reauthenticate") return Promise.resolve(undefined);
      const priorAttempts = post.mock.calls.filter((call) => call[0] === "/jobs/j1/retry").length;
      if (priorAttempts === 1) return Promise.reject(new ApiError(403, "Recent authentication required."));
      return Promise.resolve({});
    });
    render(<JobsPage />);
    await screen.findByText("Send Reminder");
    await userEvent.type(screen.getByLabelText("Reason for retry"), "Retrying after fix");
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    const dialog = await screen.findByRole("dialog", { name: "Retry job" });
    await userEvent.click(within(dialog).getByRole("button", { name: "Retry" }));

    const reauthDialog = await screen.findByRole("dialog", { name: /Confirm it.s you/i });
    await userEvent.type(within(reauthDialog).getByLabelText("Password"), "hunter2");
    await userEvent.click(within(reauthDialog).getByRole("button", { name: "Confirm" }));

    await waitFor(() =>
      expect(post.mock.calls.filter((call) => call[0] === "/jobs/j1/retry")).toHaveLength(2),
    );
  });

  it("does not offer failed-job retry section when there are no failed jobs", async () => {
    get.mockResolvedValue({ ...response, items: [{ ...failedJob, state: "completed" }] });
    render(<JobsPage />);
    await screen.findByText("Send Reminder");
    expect(screen.queryByText("Retry failed jobs")).not.toBeInTheDocument();
  });
});
