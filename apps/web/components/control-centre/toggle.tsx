import type { ChangeEvent } from "react";

/** Compact accessible switch for boolean PCC settings. */
export function CcToggle({
  label,
  name,
  defaultChecked,
  disabled,
  onChange,
}: {
  label: string;
  name: string;
  defaultChecked?: boolean;
  disabled?: boolean;
  onChange?: (event: ChangeEvent<HTMLInputElement>) => void;
}) {
  return (
    <label className="cc-toggle">
      <span>{label}</span>
      <input type="checkbox" name={name} defaultChecked={defaultChecked} disabled={disabled} onChange={onChange} />
      <span className="cc-toggle-track" aria-hidden="true"><span className="cc-toggle-thumb" /></span>
    </label>
  );
}
