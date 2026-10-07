import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import VerifyEmail from "./page";

const { post, searchParams } = vi.hoisted(() => ({
  post: vi.fn(),
  searchParams: { value: "" },
}));

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(searchParams.value),
}));

vi.mock("@mykhaya/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@mykhaya/api-client")>();
  return { ...actual, api: { ...actual.api, post } };
});

vi.mock("@/components/native-runtime", () => ({ isNativeShell: () => false }));

beforeEach(() => {
  vi.clearAllMocks();
  searchParams.value = "";
  post.mockResolvedValue({ message: "Your email is verified." });
});

describe("Founding Beta email verification continuation", () => {
  it("preserves the Beta continuation for a newly registered user", async () => {
    searchParams.value = "token=verification-token&beta=1&beta_invitation=invite-token";
    render(<VerifyEmail />);

    expect(await screen.findByRole("link", { name: "Continue to sign in" })).toHaveAttribute(
      "href",
      "/login?beta=1&beta_invitation=invite-token",
    );
  });
});
