"use client";

import { Check, Pipette } from "lucide-react";
import { contrastText, PALETTE_HEX, PALETTE_KEYS, type ColourKey } from "@mykhaya/design-tokens";
import { COLOUR_LABELS } from "./colour-swatch-picker";

function isColourKey(value: string): value is ColourKey {
  return Object.prototype.hasOwnProperty.call(PALETTE_HEX, value);
}

/** Accepts either a real hex value or (for any pre-migration data that
 *  hasn't been reloaded from the server yet) a legacy palette token name —
 *  the same two shapes design-tokens' `resolveColour` already tolerates —
 *  and always returns uppercase hex, or null for no value at all. */
function normaliseValue(value: string | null | undefined): string | null {
  if (!value) return null;
  if (isColourKey(value)) return PALETTE_HEX[value];
  return value.toUpperCase();
}

function matchingPresetKey(hex: string): ColourKey | null {
  return PALETTE_KEYS.find((key) => PALETTE_HEX[key] === hex) ?? null;
}

/** Calendar/Calendar Tag colour picker — the preset palette plus a trailing
 *  "Custom" option, shared by Calendar management and Calendar Tag
 *  management (previously each rendered its own copy of the same picker).
 *  Unlike ColourSwatchPicker (still used for member colour, which persists
 *  a palette token), this always works in real hex: `value` is a hex string,
 *  and `onChange` is always called with a hex string too — a preset click
 *  resolves to its known hex, and Custom emits whatever the native colour
 *  input returns. See docs/design/visual-identity.md and
 *  docs/architecture/adr for the calendar-colour-hex migration. */
export function CalendarColourPicker({
  value,
  onChange,
  groupLabel,
  disabled = false,
}: {
  value: string | null | undefined;
  onChange: (hex: string) => void;
  groupLabel: string;
  disabled?: boolean;
}) {
  const normalisedValue = normaliseValue(value);
  const activePreset = normalisedValue ? matchingPresetKey(normalisedValue) : null;
  // A custom colour is "active" only once it's a real value that isn't just
  // one of the presets under a different name — otherwise the Custom control
  // stays in its generic/rainbow state rather than claiming a preset's colour.
  const customActive = normalisedValue !== null && activePreset === null;

  return (
    <div className="colour-picker" role="radiogroup" aria-label={groupLabel}>
      <div className="colour-swatch-grid">
        {PALETTE_KEYS.map((key) => {
          const hex = PALETTE_HEX[key];
          const selected = activePreset === key;
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
                  "--swatch-colour": hex,
                  "--swatch-check-colour": contrastText(hex),
                } as React.CSSProperties
              }
              disabled={disabled}
              onClick={() => onChange(hex)}
            >
              {selected && <Check size={14} aria-hidden="true" strokeWidth={3} />}
            </button>
          );
        })}
        <label
          className={`colour-swatch colour-swatch-custom${customActive ? " selected" : ""}`}
          style={
            customActive && normalisedValue
              ? ({
                  "--swatch-colour": normalisedValue,
                  "--swatch-check-colour": contrastText(normalisedValue),
                } as React.CSSProperties)
              : undefined
          }
          title="Custom colour"
        >
          <input
            type="color"
            aria-label="Custom colour"
            aria-checked={customActive}
            role="radio"
            value={customActive && normalisedValue ? normalisedValue : "#888888"}
            disabled={disabled}
            onChange={(event) => onChange(event.target.value.toUpperCase())}
          />
          {customActive ? (
            <Check size={14} aria-hidden="true" strokeWidth={3} className="colour-swatch-custom-icon" />
          ) : (
            <Pipette size={14} aria-hidden="true" className="colour-swatch-custom-icon" />
          )}
        </label>
      </div>
    </div>
  );
}
