"use client";

import { BottomSheet } from "./bottom-sheet";

type ListScope = "personal" | "household";

export function ListScopeConfirmation({
  currentScope,
  onCancel,
  onConfirm,
  busy,
  error,
}: {
  currentScope: ListScope;
  onCancel: () => void;
  onConfirm: () => void;
  busy: boolean;
  error: string;
}) {
  const targetScope = currentScope === "personal" ? "household" : "personal";
  const targetLabel = targetScope === "personal" ? "Personal" : "Household";
  return (
    <BottomSheet title={`Move to ${targetLabel}?`} onDismiss={onCancel}>
      <div className="lists-scope-confirmation">
        <p>
          {targetScope === "personal"
            ? "Only you will be able to see and manage this list."
            : "This list will become visible to members of your Home who have access to Lists."}
        </p>
        {error && <p className="form-error" role="alert">{error}</p>}
        <div className="sheet-actions">
          <button type="button" className="secondary" onClick={onCancel} disabled={busy}>
            Cancel
          </button>
          <button type="button" onClick={onConfirm} disabled={busy}>
            {busy ? "Moving…" : `Move to ${targetLabel}`}
          </button>
        </div>
      </div>
    </BottomSheet>
  );
}
