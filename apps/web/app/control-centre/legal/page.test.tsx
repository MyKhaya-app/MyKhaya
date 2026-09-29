import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import LegalOverviewPage from "./page";

vi.mock("next/navigation", () => ({
  usePathname: () => "/control-centre/legal",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}));
vi.mock("@mykhaya/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@mykhaya/api-client")>();
  return { ...actual, platformApi: { get: vi.fn() } };
});
const { platformApi } = await import("@mykhaya/api-client");
const get = platformApi.get as unknown as ReturnType<typeof vi.fn>;

const documents = [
  {
    id: "doc-1",
    key: "terms",
    display_name: "Terms & Conditions",
    audience: "adult",
    action_verb: "accept",
    acceptance_required: true,
    archived_at: null,
    published_version: {
      id: "v1",
      version: "2.0",
      version_sequence: 2,
      status: "published",
      effective_date: "2026-09-01",
      published_at: "2026-09-01T09:00:00Z",
      updated_at: "2026-09-01T09:00:00Z",
      reacceptance_scope: "all_existing_users",
      change_summary: null,
      acceptance_count: 4,
    },
    draft_version: {
      id: "v2",
      version: "2.1",
      version_sequence: 3,
      status: "draft",
      effective_date: null,
      published_at: null,
      updated_at: "2026-09-05T09:00:00Z",
      reacceptance_scope: "new_users_only",
      change_summary: null,
      acceptance_count: 0,
    },
  },
];

beforeEach(() => {
  vi.clearAllMocks();
  get.mockResolvedValue(documents);
});

describe("Legal & Compliance overview", () => {
  it("shows the sub-navigation and summary cards computed from loaded documents", async () => {
    render(<LegalOverviewPage />);
    expect(await screen.findByText("Terms & Conditions")).toBeInTheDocument();
    const subnav = screen.getByRole("navigation", { name: "Legal & Compliance sections" });
    expect(within(subnav).getByRole("link", { name: "Overview" })).toBeInTheDocument();
    expect(within(subnav).getByRole("link", { name: "Documents" })).toBeInTheDocument();
    expect(within(subnav).getByText("Acceptance")).toBeInTheDocument();
    // 1 document, 1 published, 1 draft, 1 requiring all-existing-user re-acceptance.
    const cardValues = screen.getAllByText("1");
    expect(cardValues.length).toBeGreaterThanOrEqual(4);
  });

  it("offers Edit draft as the row action when a draft is open", async () => {
    render(<LegalOverviewPage />);
    await screen.findByText("Terms & Conditions");
    expect(screen.getByRole("link", { name: "Edit draft" })).toHaveAttribute(
      "href",
      "/legal/documents/doc-1",
    );
  });
});
