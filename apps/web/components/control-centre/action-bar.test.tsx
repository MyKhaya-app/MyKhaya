import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { CcActionBar } from "./action-bar";

describe("CcActionBar", () => {
  it("renders one control per action, in order", () => {
    render(
      <CcActionBar
        actions={[
          { key: "a", label: "Enable", variant: "primary" },
          { key: "b", label: "Refresh" },
          { key: "c", label: "Delete", variant: "destructive" },
        ]}
      />,
    );
    const buttons = screen.getAllByRole("button");
    expect(buttons.map((button) => button.textContent)).toEqual(["Enable", "Refresh", "Delete"]);
  });

  it("applies the variant class for primary/secondary/caution/destructive", () => {
    render(
      <CcActionBar
        actions={[
          { key: "primary", label: "Primary", variant: "primary" },
          { key: "secondary", label: "Secondary", variant: "secondary" },
          { key: "caution", label: "Caution", variant: "caution" },
          { key: "destructive", label: "Destructive", variant: "destructive" },
        ]}
      />,
    );
    expect(screen.getByRole("button", { name: "Primary" }).className).toContain("cc-action-primary");
    expect(screen.getByRole("button", { name: "Secondary" }).className).toContain("cc-action-secondary");
    expect(screen.getByRole("button", { name: "Caution" }).className).toContain("cc-action-caution");
    expect(screen.getByRole("button", { name: "Destructive" }).className).toContain(
      "cc-action-destructive",
    );
  });

  it("defaults to the secondary variant when none is given", () => {
    render(<CcActionBar actions={[{ label: "Refresh" }]} />);
    expect(screen.getByRole("button", { name: "Refresh" }).className).toContain("cc-action-secondary");
  });

  it("calls onClick when a button action is activated", async () => {
    const onClick = vi.fn();
    render(<CcActionBar actions={[{ label: "Refresh", onClick }]} />);
    await userEvent.click(screen.getByRole("button", { name: "Refresh" }));
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("renders an action with an href as a link instead of a button", () => {
    render(<CcActionBar actions={[{ label: "Open in Stripe", href: "https://stripe.com" }]} />);
    const link = screen.getByRole("link", { name: "Open in Stripe" });
    expect(link).toHaveAttribute("href", "https://stripe.com");
  });

  it("disables a button action when disabled is set", () => {
    render(<CcActionBar actions={[{ label: "Delete", disabled: true }]} />);
    expect(screen.getByRole("button", { name: "Delete" })).toBeDisabled();
  });
});
