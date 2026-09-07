import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import GlobalSecurityPage from "./page";

vi.mock("next/navigation", () => ({
  usePathname: () => "/control-centre/security",
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

const optionalPolicy = { required: false, environment_enforced: false };
const events = [
  { id: "e1", created_at: "2026-09-07T09:00:00Z", event_type: "login_failed", severity: "warning", outcome: "blocked", safe_detail: "Too many attempts" },
];

function mockLoad(policy = optionalPolicy, eventItems = events) {
  get.mockImplementation((path: string) => {
    if (path === "/auth/mfa/policy") return Promise.resolve(policy);
    if (path.startsWith("/security")) return Promise.resolve({ items: eventItems });
    return Promise.reject(new Error(`unexpected path ${path}`));
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  mockLoad();
  put.mockResolvedValue({ ...optionalPolicy, required: true });
  post.mockResolvedValue({});
});

describe("Global Security", () => {
  it("renders the MFA policy state and the security event log", async () => {
    render(<GlobalSecurityPage />);
    expect(await screen.findByText("Optional")).toBeInTheDocument();
    expect(screen.getByText("Login Failed")).toBeInTheDocument();
    expect(screen.getByText("Too many attempts")).toBeInTheDocument();
  });

  it("shows an empty state when there are no security events", async () => {
    mockLoad(optionalPolicy, []);
    render(<GlobalSecurityPage />);
    expect(await screen.findByText("No recent security events.")).toBeInTheDocument();
  });

  it("locks the toggle when the policy is environment-enforced", async () => {
    mockLoad({ required: true, environment_enforced: true });
    render(<GlobalSecurityPage />);
    expect(await screen.findByText(/permanently required in this deployment/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Require MFA|Make MFA optional/ })).not.toBeInTheDocument();
  });

  it("requires a reason and sends the exact payload with confirmed:true when changing the policy", async () => {
    render(<GlobalSecurityPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Require MFA for all administrators" }));
    const reasonInput = screen.getByLabelText("Reason for this change");
    const submit = screen.getByRole("button", { name: "Require MFA" });
    expect(submit).toBeInTheDocument();
    await userEvent.type(reasonInput, "Tightening admin security policy");
    await userEvent.click(submit);
    await waitFor(() =>
      expect(put).toHaveBeenCalledWith("/auth/mfa/policy", {
        required: true,
        reason: "Tightening admin security policy",
        confirmed: true,
      }),
    );
  });

  it("opens the reauth modal on a 403 and retries the same change once verified", async () => {
    put.mockImplementation(() => {
      const priorAttempts = put.mock.calls.length;
      if (priorAttempts === 1) return Promise.reject(new ApiError(403, "Recent authentication required."));
      return Promise.resolve({ ...optionalPolicy, required: true });
    });
    render(<GlobalSecurityPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Require MFA for all administrators" }));
    await userEvent.type(screen.getByLabelText("Reason for this change"), "Tightening admin security policy");
    await userEvent.click(screen.getByRole("button", { name: "Require MFA" }));

    const reauthDialog = await screen.findByRole("dialog", { name: /Confirm it.s you/i });
    await userEvent.type(within(reauthDialog).getByLabelText("Password"), "hunter2");
    await userEvent.click(within(reauthDialog).getByRole("button", { name: "Confirm" }));

    await waitFor(() => expect(put).toHaveBeenCalledTimes(2));
    expect(await screen.findByText("MFA is now required for every platform administrator.")).toBeInTheDocument();
  });
});
