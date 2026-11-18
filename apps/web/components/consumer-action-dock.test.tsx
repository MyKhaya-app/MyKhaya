import { readFileSync } from "node:fs";
import { resolve } from "node:path";
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

  describe("bottom action row", () => {
    function dock() {
      return document.querySelector(".consumer-action-dock") as HTMLElement;
    }

    it("puts Back first (left slot) and Add last (right slot) in one row", async () => {
      render(
        <ConsumerActionProvider>
          <Registrar />
          <ConsumerActionDock />
        </ConsumerActionProvider>,
      );
      const add = await screen.findByRole("button", { name: "Add" });
      const backButton = screen.getByRole("button", { name: "Back" });
      const children = Array.from(dock().children);
      expect(children).toEqual([backButton, add]);
      expect(backButton).toHaveClass("consumer-back-action");
      expect(add).toHaveClass("consumer-primary-action");
    });

    it("renders only Add, in the primary (right) slot, on an Add-only screen", async () => {
      route.pathname = "/calendar";
      render(
        <ConsumerActionProvider>
          <Registrar />
          <ConsumerActionDock />
        </ConsumerActionProvider>,
      );
      const add = await screen.findByRole("button", { name: "Add" });
      expect(Array.from(dock().children)).toEqual([add]);
      expect(add).toHaveClass("consumer-primary-action");
    });

    it("renders only Back, in the back (left) slot, with no empty placeholder", () => {
      route.pathname = "/driveway/vehicle-1/reminders";
      render(
        <ConsumerActionProvider>
          <ConsumerActionDock />
        </ConsumerActionProvider>,
      );
      const backButton = screen.getByRole("button", { name: "Back" });
      expect(Array.from(dock().children)).toEqual([backButton]);
      expect(backButton).toHaveClass("consumer-back-action");
    });

    it.each(["Add vehicle", "Add Budget item", "Add calendar event", "Add reminder"])(
      "shows only the visible label Add for %s, keeping the specific name accessible",
      async (label) => {
        render(
          <ConsumerActionProvider>
            <Action action={{ label, onActivate: back }} />
            <ConsumerActionDock />
          </ConsumerActionProvider>,
        );
        const add = await screen.findByRole("button", { name: label });
        expect(add).toHaveTextContent(/^Add$/);
        expect(add).toHaveAttribute("title", label);
        expect(screen.queryByText(label)).not.toBeInTheDocument();
      },
    );

    it("renders exactly one primary action and one Back", async () => {
      render(
        <ConsumerActionProvider>
          <Registrar />
          <ConsumerActionDock />
        </ConsumerActionProvider>,
      );
      await screen.findByRole("button", { name: "Add" });
      expect(document.querySelectorAll(".consumer-primary-action")).toHaveLength(1);
      expect(document.querySelectorAll(".consumer-back-action")).toHaveLength(1);
    });

    it("never adds a Back button inside the Android shell, only the primary action", async () => {
      route.platform = "android";
      route.pathname = "/driveway/vehicle-1/reminders";
      render(
        <ConsumerActionProvider>
          <Action action={{ label: "Add reminder", onActivate: back }} />
          <ConsumerActionDock />
        </ConsumerActionProvider>,
      );
      const add = await screen.findByRole("button", { name: "Add reminder" });
      expect(screen.queryByRole("button", { name: "Back" })).not.toBeInTheDocument();
      expect(Array.from(dock().children)).toEqual([add]);
    });
  });
});

// jsdom does no layout, so the placement contract is asserted on the shared
// stylesheet; scripts/action-dock-harness.mjs measures the rendered geometry.
describe("ConsumerActionDock placement styles", () => {
  const styles = readFileSync(resolve(process.cwd(), "app/styles.css"), "utf8");
  const rule = (selector: string) => {
    const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    return styles.match(new RegExp(`(?:^|\\n)${escaped} \\{([^}]*)\\}`))?.[1] ?? "";
  };

  it("lays the phone dock out as one full-width row above the bottom nav", () => {
    const dockRule = rule(".consumer-action-dock");
    expect(dockRule).toMatch(/flex-direction: row;/);
    expect(dockRule).toMatch(/left: max\(1rem, var\(--safe-left\)\);/);
    expect(dockRule).toMatch(/right: max\(1rem, var\(--safe-right\)\);/);
    expect(dockRule).toMatch(/bottom: calc\(var\(--bottom-nav-height\) \+ var\(--safe-bottom\)/);
  });

  it("pushes the primary action to the right edge so Add stays right on its own", () => {
    expect(rule(".consumer-action-dock > .consumer-primary-action")).toMatch(/margin-left: auto;/);
  });

  it("gives both actions one compact circular size", () => {
    const action = rule(".consumer-action");
    expect(action).toMatch(/border-radius: 50%;/);
    expect(action).toMatch(/height: var\(--consumer-action-size\);/);
    expect(action).toMatch(/width: var\(--consumer-action-size\);/);
    expect(styles).not.toMatch(/\.consumer-(?:back|primary)-action \{[^}]*(?:width|height):/);
  });

  it("keeps the Duo rail stacking, centred, icon-only and unaffected by the row's right slot", () => {
    const rail = rule(".app-shell.native-right-column .consumer-action-dock");
    expect(rail).toMatch(/flex-direction: column-reverse;/);
    expect(rail).toMatch(/left: auto;/);
    expect(rail).toMatch(/width: var\(--native-rail-width\);/);
    expect(rule(".app-shell.native-right-column .consumer-action-dock > .consumer-primary-action")).toMatch(/margin-left: 0;/);
    expect(rule(".app-shell.native-right-column .consumer-action span")).toMatch(/clip: rect\(0 0 0 0\);/);
  });
});
