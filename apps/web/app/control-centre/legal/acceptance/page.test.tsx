import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import AcceptancePage from "./page";

vi.mock("next/navigation", () => ({
  usePathname: () => "/control-centre/legal/acceptance",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}));
vi.mock("@mykhaya/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@mykhaya/api-client")>();
  return { ...actual, platformApi: { get: vi.fn() } };
});
const { platformApi } = await import("@mykhaya/api-client");
const get = platformApi.get as unknown as ReturnType<typeof vi.fn>;

beforeEach(() => {
  vi.clearAllMocks();
  get.mockResolvedValue({
    active_users: 2,
    up_to_date: 1,
    action_required: 1,
    pending_guardian_action: 0,
    documents: [],
    rows: [
      {
        user_id: "adult-1",
        display_name: "Adult User",
        email: "adult@example.com",
        account_type: "adult",
        documents: [],
        last_action_at: null,
        last_action: null,
        status: "up_to_date",
      },
      {
        user_id: "child-1",
        display_name: "Kid",
        email: "Managed child",
        account_type: "managed_child",
        documents: [],
        last_action_at: null,
        last_action: null,
        status: "action_required",
      },
    ],
  });
});

describe("Acceptance dashboard", () => {
  it("shows managed children as managed children rather than contact emails", async () => {
    render(<AcceptancePage />);
    expect(await screen.findByText("Kid")).toBeInTheDocument();
    expect(screen.getAllByText("Managed child").length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText("adult@example.com")).toBeInTheDocument();
    expect(screen.queryByText(/@managed\.mykhaya\.invalid/)).not.toBeInTheDocument();
  });
});
