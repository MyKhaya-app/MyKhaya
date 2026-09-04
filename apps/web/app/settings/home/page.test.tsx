import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import type { Home } from "@mykhaya/shared-types";
import HomeSettings from "./page";

// Home settings is now the home-details card only — Calendar Tags moved to
// its own More destination (app/settings/calendar-tags), and the "Khaya
// Control Centre" entry was removed entirely (see components/settings-page
// for the consolidated, grouped More menu that replaces it).

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  usePathname: () => "/settings/home",
}));

function freeHome(): Home {
  return {
    id: "home-1",
    name: "Hales Home",
    role: "owner",
    relationship: "home_admin",
    permission_profile: "home_admin",
    capabilities: ["calendar.edit_all"],
    member_count: 3,
    child_login_code: "1234",
  };
}

vi.mock("@/components/use-active-home", () => ({
  useActiveHome: () => ({
    activeHome: freeHome(),
    activeHomeId: "home-1",
    homes: [freeHome()],
    setActiveHomeId: vi.fn(),
    loading: false,
  }),
}));

vi.mock("@mykhaya/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@mykhaya/api-client")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      me: vi.fn(),
      homes: vi.fn(),
    },
  };
});

const { api } = await import("@mykhaya/api-client");

beforeEach(() => {
  vi.clearAllMocks();
  (api.me as ReturnType<typeof vi.fn>).mockResolvedValue({ id: "u1", display_name: "Owner" });
  (api.homes as ReturnType<typeof vi.fn>).mockResolvedValue([freeHome()]);
});

describe("Home settings", () => {
  it("shows the Home's name, member count and role", async () => {
    render(<HomeSettings />);

    expect(await screen.findByRole("heading", { name: "Hales Home" })).toBeInTheDocument();
    expect(screen.getByText(/3 people/)).toHaveTextContent(/your role:\s*owner/i);
  });

  it("no longer shows Calendar Tags or a Khaya Control Centre entry — both moved elsewhere", async () => {
    render(<HomeSettings />);

    await screen.findByRole("heading", { name: "Hales Home" });
    expect(screen.queryByRole("heading", { name: /calendar tags/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: /khaya control centre/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /khaya control centre/i })).not.toBeInTheDocument();
  });
});
