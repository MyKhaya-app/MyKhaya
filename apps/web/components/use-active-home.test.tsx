// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { Home } from "@mykhaya/shared-types";
import { ActiveHomeProvider, useActiveHome } from "./use-active-home";

vi.mock("./auth-provider", () => ({
  useAuth: () => ({ status: "ready" }),
}));

const { homes, homesRequest } = vi.hoisted(() => ({
  homes: [
    { id: "home-1", name: "Alpha Home" },
    { id: "home-2", name: "Beta Home" },
  ] as unknown as Home[],
  homesRequest: vi.fn(),
}));
homesRequest.mockResolvedValue(homes);
vi.mock("@mykhaya/api-client", () => ({
  api: { homes: homesRequest },
}));

function Consumer() {
  const { activeHome, setActiveHomeId } = useActiveHome();
  return (
    <>
      <span>{activeHome?.name ?? "none"}</span>
      <button type="button" onClick={() => setActiveHomeId("home-2")}>Switch</button>
    </>
  );
}

describe("ActiveHomeProvider", () => {
  it("preserves the selected home while authenticated page content changes", async () => {
    const view = render(
      <ActiveHomeProvider>
        <Consumer />
      </ActiveHomeProvider>,
    );

    await waitFor(() => expect(screen.getByText("Alpha Home")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Switch" }));
    expect(screen.getByText("Beta Home")).toBeInTheDocument();

    view.rerender(
      <ActiveHomeProvider>
        <Consumer />
      </ActiveHomeProvider>,
    );

    expect(screen.getByText("Beta Home")).toBeInTheDocument();
    expect(homesRequest).toHaveBeenCalledTimes(1);
  });
});
