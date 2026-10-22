import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import SupportPage, { metadata } from "./page";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => "/support",
}));

vi.mock("@/components/native-runtime", () => ({
  isNativeShell: () => false,
  nativePlatform: () => "web",
}));

vi.mock("@mykhaya/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@mykhaya/api-client")>();
  return { ...actual, api: { publicSignupState: vi.fn() } };
});
const { api } = await import("@mykhaya/api-client");
const signupState = api.publicSignupState as unknown as ReturnType<typeof vi.fn>;

beforeEach(() => {
  vi.clearAllMocks();
  signupState.mockResolvedValue({ signup_mode: "normal" });
});

describe("public Support page (/support)", () => {
  it("shows the heading and supporting text", () => {
    render(<SupportPage />);
    expect(screen.getByRole("heading", { level: 1, name: "We’re here to help." })).toBeInTheDocument();
    expect(
      screen.getByText(
        "Need help with MyKhaya? Whether you’re using the app or having trouble accessing your account, we’re here to help.",
      ),
    ).toBeInTheDocument();
  });

  it("sends signed-in users to the in-app Support Hub (sign-in is handled by the app)", () => {
    render(<SupportPage />);
    const card = screen.getByRole("article", { name: "Already using MyKhaya?" });
    expect(within(card).getByText(/best way to get support is through the MyKhaya Support Hub/)).toBeInTheDocument();
    expect(within(card).getByRole("link", { name: "Open Support Hub" })).toHaveAttribute("href", "/help-support");
  });

  it("offers email support for people who can't access the app", () => {
    render(<SupportPage />);
    const card = screen.getByRole("article", { name: "Can’t access MyKhaya?" });
    expect(within(card).getByText("support@mykhaya.app")).toBeInTheDocument();
    expect(within(card).getByRole("link", { name: "Email Support" })).toHaveAttribute(
      "href",
      "mailto:support@mykhaya.app",
    );
    expect(
      screen.getByText(
        "Please don’t include passwords, verification codes or sensitive personal information in support emails.",
      ),
    ).toBeInTheDocument();
  });

  it("keeps the shared marketing nav and footer, in one scope that follows the system theme", () => {
    const { container } = render(<SupportPage />);
    const root = container.querySelector(".mks.mks-page");
    expect(root).not.toBeNull();
    expect(root).not.toHaveAttribute("data-theme");
    expect(container.querySelector("[data-theme]")).toBeNull();
    expect(screen.getByRole("banner")).toBeInTheDocument();
    expect(within(screen.getByRole("contentinfo")).getByRole("link", { name: "Support" })).toHaveAttribute(
      "href",
      "/support",
    );
  });

  it("has a title, description and canonical URL", () => {
    expect(metadata.title).toBe("Support");
    expect(metadata.description).toMatch(/support@mykhaya\.app/);
    expect(metadata.alternates?.canonical).toBe("https://mykhaya.app/support");
  });
});
