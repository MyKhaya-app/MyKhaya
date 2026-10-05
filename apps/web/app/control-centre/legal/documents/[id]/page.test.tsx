import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import LegalDocumentDetailPage from "./page";
import type { LegalDocument, LegalDocumentVersionDetail } from "@/components/legal-logic";

async function renderPage() {
  await act(async () => {
    render(<LegalDocumentDetailPage params={Promise.resolve({ id: "doc-1" })} />);
  });
}

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/control-centre/legal/documents/doc-1",
}));

vi.mock("@mykhaya/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@mykhaya/api-client")>();
  return {
    ...actual,
    platformApi: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  };
});
const { platformApi, ApiError } = await import("@mykhaya/api-client");
const get = platformApi.get as unknown as ReturnType<typeof vi.fn>;
const post = platformApi.post as unknown as ReturnType<typeof vi.fn>;
const patch = platformApi.patch as unknown as ReturnType<typeof vi.fn>;
const del = platformApi.delete as unknown as ReturnType<typeof vi.fn>;

const publishedVersionSummary: LegalDocument["published_version"] = {
  id: "v1",
  version: "1.0",
  version_sequence: 1,
  status: "published",
  effective_date: "2026-09-01",
  published_at: "2026-09-01T09:00:00Z",
  updated_at: "2026-09-01T09:00:00Z",
  reacceptance_scope: "new_users_only",
  change_summary: null,
  acceptance_count: 12,
};

const baseDocument: LegalDocument = {
  id: "doc-1",
  key: "terms",
  display_name: "Terms & Conditions",
  audience: "adult",
  scope: "global",
  action_verb: "accept",
  acceptance_required: true,
  archived_at: null,
  published_version: publishedVersionSummary,
  draft_version: null,
};

const publishedVersionDetail: LegalDocumentVersionDetail = {
  ...publishedVersionSummary,
  content_markdown: "# Terms\n\nBe nice. <img src=x onerror=alert(1)>",
  created_by_administrator_id: "admin-1",
  updated_by_administrator_id: "admin-1",
  published_by_administrator_id: "admin-1",
  superseded_at: null,
  superseded_by_version_id: null,
};

function mockLoad(
  overrides: { document?: LegalDocument; versions?: LegalDocumentVersionDetail[] } = {},
) {
  const doc = overrides.document ?? baseDocument;
  const versions = overrides.versions ?? [publishedVersionDetail];
  get.mockImplementation((path: string) => {
    if (path === "/legal/documents/doc-1") return Promise.resolve(doc);
    if (path === "/legal/documents/doc-1/versions") return Promise.resolve(versions);
    if (path === "/administrators")
      return Promise.resolve([{ id: "admin-1", display_name: "Ada Admin" }]);
    return Promise.reject(new Error(`unexpected path ${path}`));
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  mockLoad();
  post.mockResolvedValue({});
  patch.mockResolvedValue({});
  del.mockResolvedValue(undefined);
});

describe("Legal document detail", () => {
  it("renders the current published version and sanitises its markdown", async () => {
    await renderPage();
    expect(await screen.findByRole("heading", { name: "Terms & Conditions" })).toBeInTheDocument();
    expect(screen.getByText("Be nice.")).toBeInTheDocument();
    // The sanitiser strips <img> entirely — no img element, and definitely
    // no onerror handler, should reach the DOM.
    expect(window.document.querySelectorAll("img")).toHaveLength(0);
    expect(screen.queryByText(/onerror/)).not.toBeInTheDocument();
  });

  it("shows an empty state when nothing has ever been published", async () => {
    mockLoad({
      document: { ...baseDocument, published_version: null },
      versions: [],
    });
    await renderPage();
    expect(await screen.findByText("This document has never been published.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Create first version" })).toBeInTheDocument();
  });

  it("switches to the Draft tab and shows the WYSIWYG editor with a live preview", async () => {
    const draftVersion = {
      ...publishedVersionDetail,
      id: "v2",
      version: "1.1",
      status: "draft" as const,
      published_at: null,
      content_markdown: "# Draft heading",
    };
    mockLoad({
      document: { ...baseDocument, draft_version: { ...publishedVersionSummary, id: "v2", version: "1.1", status: "draft" } },
      versions: [publishedVersionDetail, draftVersion],
    });
    await renderPage();
    await userEvent.click(await screen.findByRole("button", { name: /Draft \(v1.1\)/ }));
    const editor = await screen.findByTestId("legal-markdown-editor");
    expect(editor).toHaveTextContent("Draft heading");
    await userEvent.click(screen.getByRole("tab", { name: "Preview" }));
    expect(screen.getByRole("heading", { name: "Draft heading" })).toBeInTheDocument();
  });

  it("saves a draft without publishing it", async () => {
    const draftVersion = {
      ...publishedVersionDetail,
      id: "v2",
      version: "1.1",
      status: "draft" as const,
      published_at: null,
    };
    mockLoad({
      document: { ...baseDocument, draft_version: { ...publishedVersionSummary, id: "v2", version: "1.1", status: "draft" } },
      versions: [publishedVersionDetail, draftVersion],
    });
    await renderPage();
    await userEvent.click(await screen.findByRole("button", { name: /Draft \(v1.1\)/ }));
    await screen.findByTestId("legal-markdown-editor");
    await userEvent.click(screen.getByRole("button", { name: "Save draft" }));
    await waitFor(() =>
      expect(patch).toHaveBeenCalledWith(
        "/legal/documents/doc-1/versions/v2",
        expect.objectContaining({ content_markdown: draftVersion.content_markdown }),
      ),
    );
    expect(await screen.findByText("Draft saved.")).toBeInTheDocument();
    expect(post).not.toHaveBeenCalledWith(expect.stringContaining("/publish"), expect.anything());
  });

  it("discards a draft after explicit confirmation, leaving the published version untouched", async () => {
    const draftVersion = { ...publishedVersionDetail, id: "v2", version: "1.1", status: "draft" as const };
    mockLoad({
      document: { ...baseDocument, draft_version: { ...publishedVersionSummary, id: "v2", version: "1.1", status: "draft" } },
      versions: [publishedVersionDetail, draftVersion],
    });
    await renderPage();
    await userEvent.click(await screen.findByRole("button", { name: /Draft \(v1.1\)/ }));
    await userEvent.click(await screen.findByRole("button", { name: "Discard draft" }));
    const dialog = await screen.findByRole("dialog", { name: "Discard draft v1.1" });
    expect(within(dialog).getByText(/currently published version will not be affected/i)).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Discard draft" }));
    await waitFor(() => expect(del).toHaveBeenCalledWith("/legal/documents/doc-1/versions/v2"));
    expect(await screen.findByText(/Draft discarded/)).toBeInTheDocument();
  });

  it("publishes a draft with the chosen re-acceptance scope and a reason, warning on all_existing_users", async () => {
    const draftVersion = { ...publishedVersionDetail, id: "v2", version: "1.1", status: "draft" as const };
    mockLoad({
      document: { ...baseDocument, draft_version: { ...publishedVersionSummary, id: "v2", version: "1.1", status: "draft" } },
      versions: [publishedVersionDetail, draftVersion],
    });
    await renderPage();
    await userEvent.click(await screen.findByRole("button", { name: /Draft \(v1.1\)/ }));
    await userEvent.click(await screen.findByRole("button", { name: "Publish version" }));
    const dialog = await screen.findByRole("dialog", { name: /Publish Terms & Conditions v1.1/ });
    await userEvent.click(within(dialog).getByLabelText(/All existing users/));
    expect(
      within(dialog).getByText(/requires existing applicable users to complete the required legal action/i),
    ).toBeInTheDocument();
    await userEvent.type(
      within(dialog).getByLabelText(/at least 10 characters/i),
      "Material change to liability terms",
    );
    await userEvent.click(within(dialog).getByRole("button", { name: "Publish version" }));
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/legal/documents/doc-1/versions/v2/publish", {
        reacceptance_scope: "all_existing_users",
        reason: "Material change to liability terms",
      }),
    );
    expect(await screen.findByText("Version published.")).toBeInTheDocument();
  });

  it("keeps TEST publication separate and names the TEST confirmation", async () => {
    const draftVersion = { ...publishedVersionDetail, id: "v2", version: "test-0.1", status: "draft" as const };
    mockLoad({
      document: { ...baseDocument, draft_version: { ...publishedVersionSummary, id: "v2", version: "test-0.1", status: "draft" } },
      versions: [publishedVersionDetail, draftVersion],
    });
    await renderPage();
    await userEvent.click(await screen.findByRole("button", { name: /Draft \(vtest-0.1\)/ }));
    await userEvent.click(await screen.findByRole("button", { name: "Publish version" }));
    const dialog = await screen.findByRole("dialog", { name: /Publish Terms & Conditions vtest-0.1/ });
    await userEvent.click(within(dialog).getByLabelText(/Publish as TEST VERSION/));
    expect(await screen.findByRole("dialog", { name: /Publish TEST version of Terms/ })).toBeInTheDocument();
    expect(within(dialog).getByText(/excluded from public policy pages/i)).toBeInTheDocument();
    await userEvent.type(within(dialog).getByLabelText(/Reason for publishing/), "Controlled TEST publication");
    await userEvent.click(within(dialog).getByRole("button", { name: "Publish TEST version" }));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/legal/documents/doc-1/versions/v2/publish", {
      reacceptance_scope: "new_users_only",
      reason: "Controlled TEST publication",
      is_test: true,
    }));
  });

  it("shows the reauth modal on a 403 recent-auth error and retries publish after re-authenticating", async () => {
    const draftVersion = { ...publishedVersionDetail, id: "v2", version: "1.1", status: "draft" as const };
    mockLoad({
      document: { ...baseDocument, draft_version: { ...publishedVersionSummary, id: "v2", version: "1.1", status: "draft" } },
      versions: [publishedVersionDetail, draftVersion],
    });
    post.mockImplementation((path: string) => {
      if (path === "/auth/reauthenticate") return Promise.resolve(undefined);
      if (path === "/legal/documents/doc-1/versions/v2/publish") {
        const attempts = post.mock.calls.filter((call) => call[0] === path).length;
        if (attempts === 1) return Promise.reject(new ApiError(403, "Recent administrator authentication required."));
        return Promise.resolve({});
      }
      return Promise.resolve({});
    });
    await renderPage();
    await userEvent.click(await screen.findByRole("button", { name: /Draft \(v1.1\)/ }));
    await userEvent.click(await screen.findByRole("button", { name: "Publish version" }));
    const dialog = await screen.findByRole("dialog", { name: /Publish Terms & Conditions v1.1/ });
    await userEvent.type(
      within(dialog).getByLabelText(/at least 10 characters/i),
      "Routine wording clarification",
    );
    await userEvent.click(within(dialog).getByRole("button", { name: "Publish version" }));

    const reauthDialog = await screen.findByRole("dialog", { name: /Confirm it.?s you/i });
    await userEvent.type(within(reauthDialog).getByLabelText("Password"), "operator-password");
    await userEvent.click(within(reauthDialog).getByRole("button", { name: "Confirm" }));

    await waitFor(() => expect(screen.getByText("Version published.")).toBeInTheDocument());
    expect(post).toHaveBeenCalledWith("/auth/reauthenticate", { password: "operator-password" });
  });

  it("shows read-only version history and no edit action on a superseded version", async () => {
    const supersededVersion = {
      ...publishedVersionDetail,
      id: "v0",
      version: "0.9",
      status: "superseded" as const,
      superseded_at: "2026-09-01T00:00:00Z",
    };
    mockLoad({ versions: [publishedVersionDetail, supersededVersion] });
    await renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Version History" }));
    expect(await screen.findByText("v0.9")).toBeInTheDocument();
    expect(screen.getByText("Superseded")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /edit/i })).not.toBeInTheDocument();
  });
});
