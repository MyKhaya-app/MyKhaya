"use client";

import { Check } from "lucide-react";
import { contrastText, PALETTE_HEX, PALETTE_KEYS, type ColourKey } from "@mykhaya/design-tokens";

export const COLOUR_LABELS: Record<ColourKey, string> = {
  red: "Red",
  coral: "Coral",
  rust: "Rust",
  orange: "Orange",
  amber: "Amber",
  yellow: "Yellow",
  olive: "Olive",
  lime: "Lime",
  green: "Green",
  emerald: "Emerald",
  jade: "Jade",
  teal: "Teal",
  cyan: "Cyan",
  sky: "Sky",
  blue: "Blue",
  azure: "Azure",
  indigo: "Indigo",
  periwinkle: "Periwinkle",
  violet: "Violet",
  purple: "Purple",
  plum: "Plum",
  pink: "Pink",
  magenta: "Magenta",
  rose: "Rose",
  slate: "Slate",
  stone: "Stone",
  charcoal: "Charcoal",
};

/** Compact, circular colour-swatch grid shared by profile colour selection
 *  and calendar/category colour selection — one picker, one palette,
 *  everywhere a colour is chosen. Colour is never the only signal: every
 *  swatch carries a text label (visually hidden, always in the accessible
 *  name) and the selected swatch gets a visible ring plus a checkmark, not
 *  just a colour change. See docs/design/visual-identity.md. */
export function ColourSwatchPicker({
  value,
  onChange,
  groupLabel,
  disabled = false,
}: {
  value: string | null | undefined;
  onChange: (colour: ColourKey) => void;
  groupLabel: string;
  disabled?: boolean;
}) {
  return (
    <div className="colour-swatch-grid" role="radiogroup" aria-label={groupLabel}>
      {PALETTE_KEYS.map((key) => {
        const selected = value === key;
        return (
          <button
            key={key}
            type="button"
            role="radio"
            aria-checked={selected}
            aria-label={COLOUR_LABELS[key]}
            title={COLOUR_LABELS[key]}
            className={`colour-swatch${selected ? " selected" : ""}`}
            style={
              {
                "--swatch-colour": PALETTE_HEX[key],
                "--swatch-check-colour": contrastText(PALETTE_HEX[key]),
              } as React.CSSProperties
            }
            disabled={disabled}
            onClick={() => onChange(key)}
          >
            {selected && <Check size={14} aria-hidden="true" strokeWidth={3} />}
          </button>
        );
      })}
    </div>
  );
}
