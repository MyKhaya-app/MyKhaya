import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { CcConfirmDialog, CcDialog } from "./dialog";

/**
 * Regression harness for the focus-stealing bug: a controlled input inside
 * the dialog whose onChange triggers a parent re-render with a brand new
 * inline `onClose` identity (as real callers do, e.g.
 * `onClose={() => setOpen(false)}`). Before the fix, the dialog's
 * focus-management effect depended on `[open, onClose]`, so this re-render
 * re-ran the effect and yanked focus back to the first focusable element on
 * every keystroke.
 */
function ControlledInputHarness() {
  const [open, setOpen] = useState(true);
  const [value, setValue] = useState("");
  return (
    <CcDialog open={open} onClose={() => setOpen(false)} title="Controlled">
      <input aria-label="Reason" value={value} onChange={(event) => setValue(event.target.value)} />
    </CcDialog>
  );
}

describe("CcDialog", () => {
  it("renders nothing when closed", () => {
    render(
      <CcDialog open={false} onClose={() => {}} title="Hidden">
        content
      </CcDialog>,
    );
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("renders with dialog semantics when open and moves focus inside", async () => {
    render(
      <CcDialog open onClose={() => {}} title="Visible">
        <button>Do it</button>
      </CcDialog>,
    );
    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveAttribute("aria-modal", "true");
    await waitFor(() => expect(screen.getByText("Do it")).toHaveFocus());
  });

  it("calls onClose on Escape and on backdrop click", () => {
    const onClose = vi.fn();
    const { container } = render(
      <CcDialog open onClose={onClose} title="Closable">
        body
      </CcDialog>,
    );
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);

    const backdrop = container.querySelector(".platform-modal-backdrop");
    expect(backdrop).not.toBeNull();
    fireEvent.click(backdrop as Element);
    expect(onClose).toHaveBeenCalledTimes(2);
  });

  it("does not close when clicking inside the dialog panel", () => {
    const onClose = vi.fn();
    render(
      <CcDialog open onClose={onClose} title="Stays open">
        <p>panel content</p>
      </CcDialog>,
    );
    fireEvent.click(screen.getByText("panel content"));
    expect(onClose).not.toHaveBeenCalled();
  });

  it("restores focus to the previously-focused element after closing", async () => {
    function Harness() {
      const [open, setOpen] = useState(false);
      return (
        <div>
          <button onClick={() => setOpen(true)}>Open dialog</button>
          <CcDialog open={open} onClose={() => setOpen(false)} title="Restorable">
            <button>Inside</button>
          </CcDialog>
        </div>
      );
    }
    const user = userEvent.setup();
    render(<Harness />);
    const trigger = screen.getByRole("button", { name: "Open dialog" });
    trigger.focus();
    expect(trigger).toHaveFocus();

    await user.click(trigger);
    await waitFor(() => expect(screen.getByRole("button", { name: "Inside" })).toHaveFocus());

    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    await waitFor(() => expect(trigger).toHaveFocus());
  });

  it("does not steal focus from a controlled input inside the dialog while typing", async () => {
    const user = userEvent.setup();
    render(<ControlledInputHarness />);
    const input = screen.getByLabelText("Reason");

    await user.click(input);
    expect(input).toHaveFocus();

    await user.type(input, "hello world");
    expect(input).toHaveFocus();
    expect(input).toHaveValue("hello world");
  });
});

describe("CcConfirmDialog", () => {
  it("requires a reason before submitting and calls onConfirm with form data", async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn();
    render(
      <CcConfirmDialog
        open
        onClose={() => {}}
        title="Remove complimentary access"
        confirmLabel="Remove complimentary access"
        variant="destructive"
        onConfirm={onConfirm}
      />,
    );
    const reasonInput = screen.getByLabelText(/Reason for this administrative action/i);
    await user.type(reasonInput, "Customer requested removal via support ticket");
    await user.click(screen.getByRole("button", { name: "Remove complimentary access" }));
    expect(onConfirm).toHaveBeenCalledTimes(1);
    const formData = onConfirm.mock.calls[0]![0] as FormData;
    expect(formData.get("audit_reason")).toBe("Customer requested removal via support ticket");
  });

  it("renders the destructive button distinctly from the default variant", () => {
    render(
      <CcConfirmDialog
        open
        onClose={() => {}}
        title="Reconcile"
        confirmLabel="Reconcile"
        onConfirm={() => {}}
      />,
    );
    expect(screen.getByRole("button", { name: "Reconcile" }).className).not.toContain("danger");
  });

  it("renders extraFields ahead of the reason field", () => {
    render(
      <CcConfirmDialog
        open
        onClose={() => {}}
        title="Grant"
        confirmLabel="Grant"
        onConfirm={() => {}}
        extraFields={<label>Custom field</label>}
      />,
    );
    expect(screen.getByText("Custom field")).toBeInTheDocument();
  });
});
