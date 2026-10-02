// @vitest-environment jsdom
import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { PALETTE_HEX } from "@mykhaya/design-tokens";
import { CalendarColourPicker } from "./calendar-colour-picker";

describe("CalendarColourPicker — presets", () => {
  it("shows the matching preset as selected via a checked radio", () => {
    render(
      <CalendarColourPicker value={PALETTE_HEX.emerald} onChange={vi.fn()} groupLabel="Colour" />,
    );

    const emerald = screen.getByRole("radio", { name: /emerald/i });
    expect(emerald).toHaveAttribute("aria-checked", "true");
    const custom = screen.getByRole("radio", { name: /custom colour/i });
    expect(custom).toHaveAttribute("aria-checked", "false");
  });

  it("calls onChange with the preset's real hex value, not a token name", async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(<CalendarColourPicker value={null} onChange={onChange} groupLabel="Colour" />);

    await user.click(screen.getByRole("radio", { name: /^sky$/i }));

    expect(onChange).toHaveBeenCalledWith(PALETTE_HEX.sky);
  });

  it("also recognises a legacy palette token name as the current value", () => {
    render(<CalendarColourPicker value="teal" onChange={vi.fn()} groupLabel="Colour" />);

    expect(screen.getByRole("radio", { name: /^teal$/i })).toHaveAttribute("aria-checked", "true");
  });

  it("renders every preset with an accessible name and none as the only signal of selection", () => {
    render(
      <CalendarColourPicker value={PALETTE_HEX.rose} onChange={vi.fn()} groupLabel="Colour" />,
    );

    const rose = screen.getByRole("radio", { name: /^rose$/i });
    // Selection is conveyed by aria-checked (and a visible check icon), not
    // colour alone — this is the only strictly assertable part of that from
    // a test without a real renderer, but the presence of aria-checked on
    // every swatch (not just the selected one) is what makes it accessible.
    expect(rose).toHaveAttribute("aria-checked", "true");
    for (const radio of screen.getAllByRole("radio")) {
      expect(radio).toHaveAttribute("aria-checked");
      expect(radio).toHaveAccessibleName();
    }
  });
});

describe("CalendarColourPicker — custom colour", () => {
  it("shows Custom as selected and displaying the exact colour when the value matches no preset", () => {
    render(
      <CalendarColourPicker value="#123ABC" onChange={vi.fn()} groupLabel="Colour" />,
    );

    const custom = screen.getByRole("radio", { name: /custom colour/i });
    expect(custom).toHaveAttribute("aria-checked", "true");
    expect((custom as HTMLInputElement).value.toUpperCase()).toBe("#123ABC");
    // No preset is shown as selected at the same time.
    for (const radio of screen.getAllByRole("radio")) {
      if (radio !== custom) expect(radio).toHaveAttribute("aria-checked", "false");
    }
  });

  it("falls back to a generic (non-selected) state when no custom colour is active", () => {
    render(<CalendarColourPicker value={null} onChange={vi.fn()} groupLabel="Colour" />);

    expect(screen.getByRole("radio", { name: /custom colour/i })).toHaveAttribute(
      "aria-checked",
      "false",
    );
  });

  it("treats a custom colour that exactly matches a preset as that preset, not Custom", () => {
    render(
      <CalendarColourPicker value={PALETTE_HEX.violet} onChange={vi.fn()} groupLabel="Colour" />,
    );

    expect(screen.getByRole("radio", { name: /^violet$/i })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    expect(screen.getByRole("radio", { name: /custom colour/i })).toHaveAttribute(
      "aria-checked",
      "false",
    );
  });

  it("emits an uppercase hex value when a custom colour is picked via the native input", () => {
    const onChange = vi.fn();
    render(<CalendarColourPicker value={null} onChange={onChange} groupLabel="Colour" />);

    const input = screen.getByRole("radio", { name: /custom colour/i });
    // There is no real native colour-picker UI to drive in a unit test —
    // firing a change event with a target value is the standard way to
    // simulate an input[type=color] selection.
    fireEvent.change(input, { target: { value: "#a1b2c3" } });

    expect(onChange).toHaveBeenCalledWith("#A1B2C3");
  });
});

describe("CalendarColourPicker — duplicate colours across items", () => {
  it("allows two independently-rendered pickers to show the same selected colour", () => {
    const { unmount } = render(
      <CalendarColourPicker value={PALETTE_HEX.blue} onChange={vi.fn()} groupLabel="First" />,
    );
    expect(screen.getByRole("radio", { name: /^blue$/i })).toHaveAttribute("aria-checked", "true");
    unmount();

    render(<CalendarColourPicker value={PALETTE_HEX.blue} onChange={vi.fn()} groupLabel="Second" />);
    expect(screen.getByRole("radio", { name: /^blue$/i })).toHaveAttribute("aria-checked", "true");
  });
});

describe("CalendarColourPicker — group label", () => {
  it("exposes the whole picker as one labelled radiogroup", () => {
    render(
      <CalendarColourPicker value={null} onChange={vi.fn()} groupLabel="Sport colour" />,
    );

    const group = screen.getByRole("radiogroup", { name: /sport colour/i });
    expect(within(group).getAllByRole("radio").length).toBeGreaterThan(20);
  });
});
