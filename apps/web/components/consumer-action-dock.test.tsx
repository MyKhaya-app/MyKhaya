import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useMemo } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ConsumerActionDock, ConsumerActionProvider, useConsumerPrimaryAction } from "./consumer-action-dock";

const replace = vi.fn();
const back = vi.fn();

vi.mock("next/navigation", () => ({
  usePathname: () => "/lists/list-1",
  useRouter: () => ({ replace, push: vi.fn() }),
}));
vi.mock("./native-runtime", () => ({ nativePlatform: () => "ios" }));
vi.mock("./native-history-depth", () => ({ canNavigateBack: () => false }));
vi.mock("./dismissal-stack", () => ({ dismissTopmost: () => false }));

function Registrar() {
  useConsumerPrimaryAction(useMemo(() => ({ label: "Add", onActivate: back }), []));
  return null;
}

describe("ConsumerActionDock", () => {
  beforeEach(() => {
    replace.mockReset();
    back.mockReset();
  });

  it("renders Back and an explicit primary action with accessible names", async () => {
    render(
      <ConsumerActionProvider>
        <Registrar />
        <ConsumerActionDock />
      </ConsumerActionProvider>,
    );
    expect(await screen.findByRole("button", { name: "Back" })).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "Add" })).toBeInTheDocument();
  });

  it("uses the parent fallback when there is no internal history", async () => {
    const user = userEvent.setup();
    render(
      <ConsumerActionProvider>
        <Registrar />
        <ConsumerActionDock />
      </ConsumerActionProvider>,
    );
    await user.click(await screen.findByRole("button", { name: "Back" }));
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/lists"));
  });
});
