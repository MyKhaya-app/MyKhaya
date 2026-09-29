import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, render, screen } from "@testing-library/react";
import AboutLegalDocumentPage from "./page";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  usePathname: () => "/about/legal/terms",
}));

vi.mock("@mykhaya/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@mykhaya/api-client")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      me: vi.fn(),
      publicLegalDocument: vi.fn(),
      legalStatus: vi.fn(),
    },
  };
});

const { api, ApiError } = await import("@mykhaya/api-client");

const content = {
  key: "terms",
  display_name: "Terms & Conditions",
  version: "1.0",
  effective_date: "2026-09-01",
  published_at: "2026-08-20T00:00:00Z",
  change_summary: null,
  content_markdown: "# Terms\n\nBe kind.",
};

async function renderPage() {
  await act(async () => {
    render(<AboutLegalDocumentPage params={Promise.resolve({ key: "terms" })} />);
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  (api.me as ReturnType<typeof vi.fn>).mockResolvedValue({
    id: "u1",
    display_name: "Megan",
    principal_type: "adult",
  });
  (api.publicLegalDocument as ReturnType<typeof vi.fn>).mockResolvedValue(content);
  (api.legalStatus as ReturnType<typeof vi.fn>).mockResolvedValue({
    documents: [
      {
        document_key: "terms",
        display_name: "Terms & Conditions",
        audience: "adult",
        action_verb: "accept",
        current_version_id: "v1",
        current_version_label: "1.0",
        effective_date: "2026-09-01",
        required: true,
        satisfied: true,
        last_version_label: "1.0",
        last_version_id: "v1",
        last_accepted_at: "2026-09-29T14:32:00Z",
        is_test: false,
      },
    ],
    children: [],
    child_self: null,
    action_required: false,
  });
});

describe("About legal document reader", () => {
  it("renders the document title, version and sanitised content", async () => {
    await renderPage();
    expect(await screen.findByRole("heading", { name: "Terms & Conditions" })).toBeInTheDocument();
    expect(screen.getByText(/Version 1.0/)).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "Terms" })).toBeInTheDocument();
    expect(screen.getByText("Be kind.")).toBeInTheDocument();
  });

  it("shows the account's recorded acceptance status and date", async () => {
    await renderPage();
    expect(await screen.findByText(/Accepted$/)).toBeInTheDocument();
    expect(screen.getByText(/Accepted on/)).toBeInTheDocument();
  });

  it("shows a safe not-yet-available message for an unpublished document", async () => {
    (api.publicLegalDocument as ReturnType<typeof vi.fn>).mockRejectedValue(new ApiError(404, "not found"));
    await renderPage();
    expect(await screen.findByText("This document has not been published yet.")).toBeInTheDocument();
  });
});
