import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import AcceptanceHistoryPage from "./page";

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "user-1" }),
  usePathname: () => "/control-centre/legal/acceptance/user-1",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}));
vi.mock("next/link", () => ({
  default: ({ children, ...props }: { children: React.ReactNode }) => (
    <a {...props}>{children}</a>
  ),
}));
vi.mock("@/components/platform-shell", () => ({
  PlatformShell: ({ children }: { children: React.ReactNode }) => (
    <>{children}</>
  ),
}));
vi.mock("@/components/control-centre/page-shell", () => ({
  CcPage: ({ children }: { children: React.ReactNode }) => (
    <main>{children}</main>
  ),
}));
vi.mock("@/components/control-centre/page-header", () => ({
  CcPageHeader: ({ title }: { title: React.ReactNode }) => <h1>{title}</h1>,
}));
vi.mock("@/components/control-centre/legal-subnav", () => ({
  CcLegalSubnav: () => null,
}));
vi.mock("@/components/control-centre/status-message", () => ({
  CcNotice: ({ children }: { children: React.ReactNode }) => (
    <div>{children}</div>
  ),
}));
vi.mock("@mykhaya/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@mykhaya/api-client")>();
  return { ...actual, platformApi: { get: vi.fn(), post: vi.fn() } };
});

const { platformApi } = await import("@mykhaya/api-client");
const get = platformApi.get as unknown as ReturnType<typeof vi.fn>;
const post = platformApi.post as unknown as ReturnType<typeof vi.fn>;

beforeEach(() => {
  vi.clearAllMocks();
  post.mockResolvedValue({ status: "queued" });
  get.mockResolvedValue({
    user_id: "user-1",
    display_name: "Synthetic User",
    email: "synthetic@example.test",
    account_type: "adult",
    current_status: [],
    history: [
      {
        id: "acceptance-ready",
        display_name: "Terms & Conditions",
        document_id: "terms",
        version: "1.3",
        version_id: "terms-v13",
        record_type: "user_acceptance",
        context: "signup",
        platform: "web",
        created_at: "2026-11-08T12:00:00Z",
        child_profile_id: null,
        evidence_status: "sent",
        email_status: "sent",
        pdf_available: true,
        evidence_id: "evidence-ready",
      },
      {
        id: "acceptance-generating",
        display_name: "Privacy",
        document_id: "privacy",
        version: "1.0",
        version_id: "privacy-v1",
        record_type: "user_acceptance",
        context: "signup",
        platform: "web",
        created_at: "2026-11-08T12:01:00Z",
        child_profile_id: null,
        evidence_status: "generating",
        email_status: "pending",
        pdf_available: false,
        evidence_id: "evidence-generating",
      },
      {
        id: "acceptance-failed",
        display_name: "Children's Privacy",
        document_id: "children",
        version: "1.0",
        version_id: "children-v1",
        record_type: "user_acceptance",
        context: "signup",
        platform: "web",
        created_at: "2026-11-08T12:02:00Z",
        child_profile_id: null,
        evidence_status: "failed",
        email_status: "pending",
        evidence_last_error: "PDF generation failed permanently.",
        pdf_available: false,
        evidence_id: "evidence-failed",
      },
      {
        id: "acceptance-historical",
        display_name: "Cookies",
        document_id: "cookies",
        version: "1.0",
        version_id: "cookies-v1",
        record_type: "user_acceptance",
        context: "signup",
        platform: "web",
        created_at: "2026-11-08T12:03:00Z",
        child_profile_id: null,
        evidence_status: null,
        email_status: null,
        pdf_available: false,
        evidence_id: null,
      },
    ],
  });
});

describe("Acceptance history evidence actions", () => {
  it("only downloads ready evidence and exposes retry for failed generation", async () => {
    render(<AcceptanceHistoryPage />);

    expect(await screen.findByText(/PDF ready/)).toBeInTheDocument();
    expect(screen.getByText(/Generating PDF/)).toBeInTheDocument();
    expect(
      screen.getByText(
        (_, element) =>
          element?.tagName === "P" &&
          Boolean(
            element?.textContent?.includes("Evidence: PDF generation failed"),
          ),
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/PDF not available for historical acceptance/),
    ).toBeInTheDocument();
    expect(screen.getByText("Download PDF evidence")).toBeInTheDocument();
    expect(screen.getAllByText("View exact version")).toHaveLength(4);
    expect(screen.getByText("Resend PDF")).toBeInTheDocument();
    expect(screen.getByText("Retry PDF generation")).toBeInTheDocument();
    expect(
      screen.getAllByRole("link", { name: "Download PDF evidence" }),
    ).toHaveLength(1);

    fireEvent.click(screen.getByText("Retry PDF generation"));
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith(
        "/compliance/acceptance/user-1/evidence/evidence-failed/retry",
        {},
      ),
    );
  });
});
