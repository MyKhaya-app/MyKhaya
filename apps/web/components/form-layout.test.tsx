// @vitest-environment jsdom
import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { FormField, FormLayout, FormRow, FormSection, FormSheet } from "./form-layout";

vi.mock("./native-runtime", () => ({ isNativeShell: () => false }));

// Rendered geometry is covered by scripts/form-layout-harness.mjs (real
// Chromium layout); these tests cover structure and accessibility wiring.

describe("FormField", () => {
  it("associates the label, help text and error with the control", () => {
    render(
      <FormField label="Amount" hint="In pounds" error="Enter an amount">
        {(control) => <input {...control} type="number" />}
      </FormField>,
    );
    const input = screen.getByLabelText("Amount");
    expect(input).toHaveAttribute("aria-invalid", "true");
    const describedBy = input.getAttribute("aria-describedby")!.split(" ");
    expect(describedBy.map((id) => document.getElementById(id)!.textContent)).toEqual(["In pounds", "Enter an amount"]);
  });

  it("leaves a valid control without error wiring", () => {
    render(<FormField label="Name">{(control) => <input {...control} />}</FormField>);
    const input = screen.getByLabelText("Name");
    expect(input).not.toHaveAttribute("aria-invalid");
    expect(input).not.toHaveAttribute("aria-describedby");
  });
});

describe("FormSection and FormRow", () => {
  it("groups fields in a named fieldset with the grid on an inner element", () => {
    const { container } = render(
      <FormSection title="Destination 1" framed actions={<button type="button">Remove</button>}>
        <FormRow>
          <FormField label="Start time">{(control) => <input {...control} type="time" />}</FormField>
          <FormField label="End time">{(control) => <input {...control} type="time" />}</FormField>
        </FormRow>
      </FormSection>,
    );
    const group = screen.getByRole("group", { name: "Destination 1" });
    expect(group).toHaveClass("form-section", "form-section-framed");
    expect(group.querySelector(":scope > .form-section-body > .form-row")).not.toBeNull();
    expect(within(group).getByLabelText("Start time")).toBeInTheDocument();
    expect(container.querySelector(".form-section-actions button")).toHaveTextContent("Remove");
  });

  it("passes column count and minimum column width to the CSS", () => {
    const { container } = render(<FormRow columns={3} minColumnWidth="10rem"><span /></FormRow>);
    const row = container.querySelector(".form-row") as HTMLElement;
    expect(row.style.getPropertyValue("--form-row-columns")).toBe("3");
    expect(row.style.getPropertyValue("--form-row-min")).toBe("10rem");
  });

  it("renders a form element only when given a submit handler", () => {
    const onSubmit = vi.fn((event: React.FormEvent<HTMLFormElement>) => event.preventDefault());
    const { container, rerender } = render(<FormLayout><button>Go</button></FormLayout>);
    expect(container.querySelector("form")).toBeNull();
    rerender(<FormLayout onSubmit={onSubmit}><button>Go</button></FormLayout>);
    fireEvent.click(screen.getByRole("button", { name: "Go" }));
    expect(onSubmit).toHaveBeenCalledTimes(1);
  });
});

describe("FormSheet", () => {
  it("offers Cancel in the footer as well as the header close button", () => {
    const onDismiss = vi.fn();
    render(
      <FormSheet title="Copy event" onDismiss={onDismiss} primaryAction={<button type="button">Copy event</button>}>
        <p>Body</p>
      </FormSheet>,
    );
    const dialog = screen.getByRole("dialog", { name: "Copy event" });
    expect(dialog).toHaveClass("has-footer");
    const footer = dialog.querySelector(".sheet-footer") as HTMLElement;
    const buttons = within(footer).getAllByRole("button");
    expect(buttons.map((button) => button.textContent)).toEqual(["Copy event", "Cancel"]);
    fireEvent.click(within(footer).getByRole("button", { name: "Cancel" }));
    fireEvent.click(screen.getByRole("button", { name: "Close dialog" }));
    expect(onDismiss).toHaveBeenCalledTimes(2);
  });

  it("ignores every dismissal path while busy", () => {
    const onDismiss = vi.fn();
    render(
      <FormSheet title="Copy event" onDismiss={onDismiss} busy primaryAction={<button type="button">Copying…</button>}>
        <p>Body</p>
      </FormSheet>,
    );
    expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Close dialog" }));
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onDismiss).not.toHaveBeenCalled();
  });
});
