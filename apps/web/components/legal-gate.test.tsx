// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { LegalGate } from "./legal-gate";

const { acceptLegalDocument, legalVersion, refreshLegalStatus, clearSession, post, replace } = vi.hoisted(() => ({
  acceptLegalDocument: vi.fn().mockResolvedValue(undefined),
  legalVersion: vi.fn().mockResolvedValue({
  key: "test-terms",
  display_name: "TEST Terms & Conditions",
  version: "test-0.1",
  effective_date: null,
  published_at: "2026-09-29T12:00:00Z",
  change_summary: "Controlled browser test version.",
  content_markdown: "# TEST DOCUMENT — FOR MYKHAYA FUNCTIONAL TESTING ONLY\n\nPlease review this exact version.",
  }),
  refreshLegalStatus: vi.fn().mockResolvedValue(null),
  clearSession: vi.fn(),
  post: vi.fn().mockResolvedValue(undefined),
  replace: vi.fn(),
}));

vi.mock("next/navigation", () => ({ useRouter: () => ({ replace }) }));
vi.mock("./auth-provider", () => ({
  useAuth: () => ({
    user: { id: "user-1", principal_type: "adult" },
    legalStatus: {
      action_required: true,
      documents: [{
        document_key: "test-terms",
        display_name: "TEST Terms & Conditions",
        action_verb: "accept",
        current_version_id: "version-1",
        current_version_label: "test-0.1",
        effective_date: null,
        required: true,
        satisfied: false,
        is_test: true,
      }],
      children: [],
      child_self: null,
    },
    refreshLegalStatus,
    clearSession,
  }),
}));
vi.mock("@mykhaya/api-client", () => ({
  api: { legalVersion, acceptLegalDocument, post },
  ApiError: class ApiError extends Error {},
}));
vi.mock("./native-runtime", () => ({ isNativeShell: () => false, nativePlatform: () => "web" }));

beforeEach(() => {
  vi.clearAllMocks();
  window.scrollTo = vi.fn();
});

describe("LegalGate", () => {
  it("brands test legal requirements and accepts the exact displayed version", async () => {
    const { container } = render(<LegalGate />);

    expect(container.querySelector(".legal-gate-brand img")).toHaveAttribute("src", "/images/mykhaya-logo.png");
    expect(screen.getByText("TEST LEGAL FLOW")).toBeInTheDocument();
    expect(await screen.findByText("test-0.1")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Review document" }));
    expect(await screen.findByText("TEST DOCUMENT — FOR MYKHAYA FUNCTIONAL TESTING ONLY")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Accept and continue" }));
    await waitFor(() => expect(acceptLegalDocument).toHaveBeenCalledWith({
      document_key: "test-terms",
      document_version_id: "version-1",
      context: "policy_update",
      platform: "web",
    }));
  });

  it("confirms rejection, signs out, and does not create acceptance", async () => {
    render(<LegalGate />);

    expect(screen.queryByText("Terms & Conditions")).not.toBeInTheDocument();
    expect(screen.queryByText("Privacy Policy")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Reject and sign out" }));

    expect(screen.getByRole("dialog")).toHaveTextContent("Reject updated Terms?");
    expect(within(screen.getByRole("dialog")).getByText(/You won.t be able to continue/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Reject and sign out" }));
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Reject and sign out" }));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/auth/logout", {}));
    expect(acceptLegalDocument).not.toHaveBeenCalled();
    expect(clearSession).toHaveBeenCalled();
    expect(replace).toHaveBeenCalledWith("/login");
  });
});
