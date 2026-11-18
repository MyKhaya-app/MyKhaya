import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useMemo } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ConsumerActionDock, ConsumerActionProvider, useConsumerPrimaryAction, type ConsumerPrimaryAction } from "./consumer-action-dock";

const replace = vi.fn();
const back = vi.fn();
const push = vi.hoisted(() => vi.fn());
const route = vi.hoisted(() => ({ pathname: "/lists/list-1", platform: "ios" }));

vi.mock("next/navigation", () => ({
  usePathname: () => route.pathname,
  useRouter: () => ({ replace, push }),
}));
vi.mock("./native-runtime", () => ({ nativePlatform: () => route.platform }));
vi.mock("./native-history-depth", () => ({ canNavigateBack: () => false }));
vi.mock("./dismissal-stack", () => ({ dismissTopmost: () => false }));

function Action({ action }: { action: ConsumerPrimaryAction }) {
  const { label, href, enabled, onActivate } = action;
  useConsumerPrimaryAction(useMemo(() => ({ label, href, enabled, onActivate }), [label, href, enabled, onActivate]));
  return null;
}

function Registrar() {
  useConsumerPrimaryAction(useMemo(() => ({ label: "Add", onActivate: back }), []));
  return null;
}

describe("ConsumerActionDock", () => {
  beforeEach(() => {
    replace.mockReset();
    back.mockReset();
    push.mockReset();
    route.pathname = "/lists/list-1";
    route.platform = "ios";
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

  it("runs the registered callback when the primary action is pressed", async () => {
    const user = userEvent.setup();
    render(
      <ConsumerActionProvider>
        <Registrar />
        <ConsumerActionDock />
      </ConsumerActionProvider>,
    );
    await user.click(await screen.findByRole("button", { name: "Add" }));
    expect(back).toHaveBeenCalledOnce();
    expect(push).not.toHaveBeenCalled();
  });

  it("navigates to an href action instead of calling its callback", async () => {
    const user = userEvent.setup();
    const onActivate = vi.fn();
    render(
      <ConsumerActionProvider>
        <Action action={{ label: "Add vehicle", href: "/driveway/add", onActivate }} />
        <ConsumerActionDock />
      </ConsumerActionProvider>,
    );
    await user.click(await screen.findByRole("button", { name: "Add vehicle" }));
    expect(push).toHaveBeenCalledExactlyOnceWith("/driveway/add");
    expect(onActivate).not.toHaveBeenCalled();
  });

  it("hides a registered action while it is not enabled", async () => {
    route.platform = "web";
    const { rerender } = render(
      <ConsumerActionProvider>
        <Action action={{ label: "Add", onActivate: back, enabled: false }} />
        <ConsumerActionDock />
      </ConsumerActionProvider>,
    );
    await waitFor(() => expect(screen.queryByRole("button", { name: "Add" })).not.toBeInTheDocument());
    expect(document.querySelector(".consumer-action-dock")).toBeNull();
    rerender(
      <ConsumerActionProvider>
        <Action action={{ label: "Add", onActivate: back, enabled: true }} />
        <ConsumerActionDock />
      </ConsumerActionProvider>,
    );
    expect(await screen.findByRole("button", { name: "Add" })).toBeInTheDocument();
  });

  it("removes the action when the registering page unmounts", async () => {
    route.platform = "web";
    const { rerender } = render(
      <ConsumerActionProvider>
        <Registrar />
        <ConsumerActionDock />
      </ConsumerActionProvider>,
    );
    expect(await screen.findByRole("button", { name: "Add" })).toBeInTheDocument();
    rerender(
      <ConsumerActionProvider>
        <ConsumerActionDock />
      </ConsumerActionProvider>,
    );
    await waitFor(() => expect(screen.queryByRole("button", { name: "Add" })).not.toBeInTheDocument());
  });

  it("shows no Back on a root tab route, only the primary action", async () => {
    route.pathname = "/calendar";
    render(
      <ConsumerActionProvider>
        <Registrar />
        <ConsumerActionDock />
      </ConsumerActionProvider>,
    );
    expect(await screen.findByRole("button", { name: "Add" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Back" })).not.toBeInTheDocument();
  });

  it("uses a nested route's own parent as the Back fallback", async () => {
    const user = userEvent.setup();
    route.pathname = "/driveway/vehicle-1/reminders";
    render(
      <ConsumerActionProvider>
        <ConsumerActionDock />
      </ConsumerActionProvider>,
    );
    await user.click(await screen.findByRole("button", { name: "Back" }));
    expect(replace).toHaveBeenCalledWith("/driveway/vehicle-1");
  });

  it("shows no Back outside the iOS shell", () => {
    route.platform = "web";
    render(
      <ConsumerActionProvider>
        <ConsumerActionDock />
      </ConsumerActionProvider>,
    );
    expect(screen.queryByRole("button", { name: "Back" })).not.toBeInTheDocument();
  });
});
