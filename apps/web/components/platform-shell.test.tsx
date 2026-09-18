import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { PlatformShell } from "./platform-shell";

vi.mock("next/navigation", () => ({
  usePathname: () => "/control-centre/users",
  useRouter: () => ({ replace: vi.fn() }),
}));

vi.mock("@mykhaya/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@mykhaya/api-client")>();
  return {
    ...actual,
    platformApi: {
      get: vi.fn().mockResolvedValue({
        id: "operator-1",
        email: "operator@example.com",
        display_name: "Operator One",
        role: "platform_owner",
        mfa_enrolled: true,
        session_status: "full",
      }),
      post: vi.fn(),
    },
  };
});

describe("PlatformShell navigation groups", () => {
  beforeEach(() => window.localStorage.clear());

  it("renders groups expanded and collapses them with accessible state", async () => {
    const user = userEvent.setup();
    render(
      <PlatformShell>
        <p>Content</p>
      </PlatformShell>,
    );

    const people = screen.getByRole("button", { name: "People" });
    expect(people).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("link", { name: "Users" })).toBeInTheDocument();

    await user.click(people);
    expect(people).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("link", { name: "Users" })).not.toBeInTheDocument();
    expect(JSON.parse(window.localStorage.getItem("mykhaya.pcc.nav-groups") ?? "{}")).toMatchObject({ People: false });
  });

  it("keeps the active route group expanded after a stored collapse", async () => {
    window.localStorage.setItem("mykhaya.pcc.nav-groups", JSON.stringify({ People: false }));
    render(
      <PlatformShell>
        <p>Content</p>
      </PlatformShell>,
    );

    expect(await screen.findByRole("button", { name: "People" })).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("link", { name: "Users" })).toHaveClass("active");
  });
});
