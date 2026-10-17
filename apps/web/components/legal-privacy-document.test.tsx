import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, render, screen } from "@testing-library/react";
import { LegalPrivacyDocument } from "./legal-privacy-document";

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

const LONG_URL = "https://mykhaya.app/legal/privacy/a-very-long-path-segment-without-any-natural-break-points";

const content = {
  key: "privacy",
  display_name: "Privacy Notice",
  version: "2.1",
  effective_date: "2026-09-01",
  published_at: "2026-08-20T00:00:00Z",
  change_summary: null,
  content_markdown: `# Privacy Notice\n\n## Who we are\n\nWe look after your data.\n\n- One\n- Two\n\nSee ${LONG_URL}.`,
};

async function renderDocument() {
  await act(async () => {
    render(<LegalPrivacyDocument documentKey="privacy" />);
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  (api.me as ReturnType<typeof vi.fn>).mockResolvedValue({ id: "u1", display_name: "Megan", principal_type: "adult" });
  (api.publicLegalDocument as ReturnType<typeof vi.fn>).mockResolvedValue(content);
  (api.legalStatus as ReturnType<typeof vi.fn>).mockResolvedValue({
    documents: [
      {
        document_key: "privacy",
        display_name: "Privacy Notice",
        audience: "adult",
        action_verb: "acknowledge",
        current_version_id: "v2",
        current_version_label: "2.1",
        effective_date: "2026-09-01",
        required: true,
        satisfied: true,
        last_version_label: "2.1",
        last_version_id: "v2",
        last_accepted_at: "2026-09-29T14:32:00Z",
        is_test: false,
      },
    ],
    children: [],
    child_self: null,
    action_required: false,
  });
});

describe("Legal & Privacy document reader", () => {
  it("renders version, effective date and the document inside the padded legal card", async () => {
    await renderDocument();
    const meta = await screen.findByText(/Version 2\.1 · Effective/);
    const card = meta.closest("section");
    expect(card).toHaveClass("card", "legal-document-card");
    expect(meta).toHaveClass("legal-meta");
    const prose = card?.querySelector(".legal-prose");
    expect(prose).not.toBeNull();
    expect(screen.getByRole("heading", { level: 1, name: "Privacy Notice" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 2, name: "Who we are" })).toBeInTheDocument();
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
    expect(prose?.textContent).toContain(LONG_URL);
  });

  it("shows the account's recorded status without altering it", async () => {
    await renderDocument();
    expect(await screen.findByText(/Acknowledged on/)).toBeInTheDocument();
    expect(api.legalStatus).toHaveBeenCalled();
  });

  it("shows a safe message for an unpublished document", async () => {
    (api.publicLegalDocument as ReturnType<typeof vi.fn>).mockRejectedValue(new ApiError(404, "not found"));
    await renderDocument();
    expect(await screen.findByText("This document has not been published yet.")).toBeInTheDocument();
  });
});
