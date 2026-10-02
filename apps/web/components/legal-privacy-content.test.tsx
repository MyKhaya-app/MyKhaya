import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { LegalPrivacyContent } from "./legal-privacy-content";

vi.mock("@mykhaya/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@mykhaya/api-client")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      me: vi.fn(),
      publicLegalDocuments: vi.fn(),
      legalStatus: vi.fn(),
    },
  };
});

const { api } = await import("@mykhaya/api-client");

const terms = {
  key: "terms",
  display_name: "Terms & Conditions",
  audience: "adult",
  current_version: "1.0",
  effective_date: "2026-09-01",
};

const emptyStatus = { documents: [], children: [], child_self: null, action_required: false };

beforeEach(() => {
  vi.clearAllMocks();
  (api.me as ReturnType<typeof vi.fn>).mockResolvedValue({ id: "u1", display_name: "Megan", principal_type: "adult" });
  (api.legalStatus as ReturnType<typeof vi.fn>).mockResolvedValue(emptyStatus);
});

describe("Legal & Privacy content", () => {
  it("shows the polished empty state when no documents are published", async () => {
    (api.publicLegalDocuments as ReturnType<typeof vi.fn>).mockResolvedValue([]);
    render(<LegalPrivacyContent />);
    expect(await screen.findByRole("heading", { name: "No legal documents published yet" })).toBeInTheDocument();
    expect(screen.getByText("Keeping you informed")).toBeInTheDocument();
  });

  it("shows published documents, friendly unrecorded wording, and a tappable reader link", async () => {
    (api.publicLegalDocuments as ReturnType<typeof vi.fn>).mockResolvedValue([terms]);
    render(<LegalPrivacyContent />);
    expect(await screen.findByText("Terms & Conditions")).toBeInTheDocument();
    expect(screen.getByText("No version recorded")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Terms & Conditions/ })).toHaveAttribute("href", "/settings/legal?document=terms");
    expect(screen.getByText(/Version 1.0/)).toBeInTheDocument();
  });

  it("shows recorded status without the old awkward none wording", async () => {
    (api.publicLegalDocuments as ReturnType<typeof vi.fn>).mockResolvedValue([terms]);
    (api.legalStatus as ReturnType<typeof vi.fn>).mockResolvedValue({
      documents: [{ document_key: "terms", display_name: "Terms & Conditions", action_verb: "accept", current_version_id: "v1", current_version_label: "1.0", effective_date: "2026-09-01", required: true, satisfied: true, last_version_label: "1.0", last_version_id: "v1", last_accepted_at: "2026-09-29T14:32:00Z", is_test: false }],
      children: [], child_self: null, action_required: false,
    });
    render(<LegalPrivacyContent />);
    expect(await screen.findByText("Accepted")).toBeInTheDocument();
    expect(screen.queryByText(/last recorded version none/i)).not.toBeInTheDocument();
  });
});
