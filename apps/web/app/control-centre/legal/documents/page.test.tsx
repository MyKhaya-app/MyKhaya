import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import LegalDocumentsPage from "./page";

vi.mock("next/navigation", () => ({
  usePathname: () => "/control-centre/legal/documents",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}));
vi.mock("@mykhaya/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@mykhaya/api-client")>();
  return { ...actual, platformApi: { get: vi.fn() } };
});
const { platformApi, ApiError } = await import("@mykhaya/api-client");
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
      version: "1.0",
      version_sequence: 1,
      status: "published",
      effective_date: "2026-09-01",
      published_at: "2026-09-01T09:00:00Z",
      updated_at: "2026-09-01T09:00:00Z",
      reacceptance_scope: "new_users_only",
      change_summary: null,
      acceptance_count: 4,
    },
    draft_version: null,
  },
  {
    id: "doc-2",
    key: "cookies",
    display_name: "Cookie Policy",
    audience: "adult",
    action_verb: "acknowledge",
    acceptance_required: false,
    archived_at: null,
    published_version: null,
    draft_version: null,
  },
];

beforeEach(() => {
  vi.clearAllMocks();
  get.mockResolvedValue(documents);
});

describe("Legal documents list", () => {
  it("renders documents with status and links to the detail page", async () => {
    render(<LegalDocumentsPage />);
    expect(await screen.findByText("Terms & Conditions")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Terms & Conditions" })).toHaveAttribute(
      "href",
      "/legal/documents/doc-1",
    );
    expect(screen.getByText("Published")).toBeInTheDocument();
    expect(screen.getByText("Not published")).toBeInTheDocument();
    expect(screen.getByText("Cookie Policy")).toBeInTheDocument();
    expect(screen.getByText("Not required")).toBeInTheDocument();
  });

  it("offers a link to create a new document", async () => {
    render(<LegalDocumentsPage />);
    await screen.findByText("Terms & Conditions");
    expect(screen.getByRole("link", { name: "New document" })).toHaveAttribute(
      "href",
      "/legal/documents/new",
    );
  });

  it("shows a safe error message when loading fails", async () => {
    get.mockRejectedValue(new ApiError(500, "Service unavailable."));
    render(<LegalDocumentsPage />);
    expect(await screen.findByText(/Service unavailable\./)).toBeInTheDocument();
  });
});
