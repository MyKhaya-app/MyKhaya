"use client";

import { FormEvent, useEffect, useState } from "react";
import { api, type BudgetCategory, type BudgetSpendingEntry } from "@mykhaya/api-client";
import { BottomSheet } from "@/components/bottom-sheet";
import { FormField, FormLayout, FormRow, FormSheet } from "@/components/form-layout";
import { BudgetAmountField, useBudgetFieldErrors } from "./budget-form-fields";
import { ENTRY_FIELD_MESSAGES } from "./budget-entry-sheet";

export function BudgetEditEntrySheet({ homeId, entry, onClose, onSaved }: { homeId: string; entry: BudgetSpendingEntry; onClose: () => void; onSaved: () => void | Promise<void> }) {
  const [categories, setCategories] = useState<BudgetCategory[]>([]);
  const [category, setCategory] = useState(entry.category_id);
  const [description, setDescription] = useState(entry.description);
  const [amount, setAmount] = useState(String(entry.amount));
  const [spentOn, setSpentOn] = useState(entry.spent_on);
  const [note, setNote] = useState(entry.note ?? "");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const fields = useBudgetFieldErrors(ENTRY_FIELD_MESSAGES);

  useEffect(() => { api.budgetCategories(homeId).then(setCategories).catch(() => setError("Couldn’t load categories. Please try again.")); }, [homeId]);

  async function save(event: FormEvent) {
    event.preventDefault();
    if (saving) return;
    if (!fields.check()) {
      setError("");
      return;
    }
    setSaving(true);
    setError("");
    try {
      // Changing category off the linked fixed item's own category clears the
      // link (this sheet has no fixed-item selector of its own); otherwise the
      // existing link is preserved so payment status isn't reset by unrelated edits.
      const budgetMonthItemId = category === entry.category_id ? entry.budget_month_item_id ?? null : null;
      await api.updateBudgetEntry(homeId, entry.id, { category_id: category, description, amount: Number(amount), spent_on: spentOn, note: note.trim() || null, budget_month_item_id: budgetMonthItemId });
      await onSaved();
      onClose();
    } catch {
      setError("Couldn’t save spending entry. Please try again.");
    } finally {
      setSaving(false);
    }
  }

  async function remove() {
    setSaving(true);
    setError("");
    try {
      await api.deleteBudgetEntry(homeId, entry.id);
      await onSaved();
      onClose();
    } catch {
      setError("Couldn’t delete spending entry. Please try again.");
      setSaving(false);
    }
  }

  return <>
    <FormSheet
      title="Edit spending entry"
      onDismiss={onClose}
      busy={saving}
      primaryAction={<button type="submit" form="budget-edit-entry-form" disabled={saving}>{saving ? "Saving…" : "Save changes"}</button>}
    >
      <FormLayout id="budget-edit-entry-form" ref={fields.formRef} onSubmit={save}>
        {error && !confirmDelete && <p className="notice error" role="alert">{error}</p>}
        <FormField label="Category">
          {(control) => <select {...control} value={category} onChange={(event) => setCategory(event.target.value)}>{categories.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select>}
        </FormField>
        <FormField label="Description" error={fields.errors.description}>
          {(control) => <input {...control} name="description" value={description} onChange={(event) => { setDescription(event.target.value); fields.clear("description"); }} required />}
        </FormField>
        <FormRow minColumnWidth="10rem">
          <BudgetAmountField label="Amount" name="amount" min="0.01" value={amount} onChange={(value) => { setAmount(value); fields.clear("amount"); }} error={fields.errors.amount} />
          <FormField label="Date" error={fields.errors.spentOn}>
            {(control) => <input {...control} name="spentOn" type="date" value={spentOn} onChange={(event) => { setSpentOn(event.target.value); fields.clear("spentOn"); }} required />}
          </FormField>
        </FormRow>
        <FormField label="Note (optional)">
          {(control) => <textarea {...control} value={note} onChange={(event) => setNote(event.target.value)} maxLength={1000} rows={3} />}
        </FormField>
        <button type="button" className="budget-destructive-link" onClick={() => setConfirmDelete(true)} disabled={saving}>Delete spending entry</button>
      </FormLayout>
    </FormSheet>
    {confirmDelete && <BottomSheet title="Delete spending entry?" onDismiss={() => !saving && setConfirmDelete(false)}>
      <div className="budget-destructive-sheet"><p>This will remove “{entry.description}” and update entry-based actuals. Manual actuals are unchanged.</p>{error && <p role="alert">{error}</p>}<button type="button" className="budget-destructive-button" onClick={() => void remove()} disabled={saving}>{saving ? "Deleting…" : "Delete spending entry"}</button><button type="button" className="budget-secondary-button" onClick={() => setConfirmDelete(false)} disabled={saving}>Cancel</button></div>
    </BottomSheet>}
  </>;
}
