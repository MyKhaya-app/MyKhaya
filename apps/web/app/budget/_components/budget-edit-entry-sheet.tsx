"use client";

import { FormEvent, useEffect, useState } from "react";
import { api, type BudgetCategory, type BudgetSpendingEntry } from "@mykhaya/api-client";
import { BottomSheet } from "@/components/bottom-sheet";

export function BudgetEditEntrySheet({ homeId, entry, onClose, onSaved }: { homeId: string; entry: BudgetSpendingEntry; onClose: () => void; onSaved: () => void }) {
  const [categories, setCategories] = useState<BudgetCategory[]>([]);
  const [category, setCategory] = useState(entry.category_id);
  const [description, setDescription] = useState(entry.description);
  const [amount, setAmount] = useState(String(entry.amount));
  const [spentOn, setSpentOn] = useState(entry.spent_on);
  const [note, setNote] = useState(entry.note ?? "");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);

  useEffect(() => { api.budgetCategories(homeId).then(setCategories).catch(() => setError("Couldn’t load categories. Please try again.")); }, [homeId]);

  async function save(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    setError("");
    try {
      await api.updateBudgetEntry(homeId, entry.id, { category_id: category, description, amount: Number(amount), spent_on: spentOn, note: note.trim() || null });
      onSaved();
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
      onSaved();
      onClose();
    } catch {
      setError("Couldn’t delete spending entry. Please try again.");
      setSaving(false);
    }
  }

  return <>
    <BottomSheet title="Edit spending entry" onDismiss={() => !saving && onClose()}>
      <form className="budget-sheet-form" onSubmit={save}>
        <label htmlFor="edit-entry-category">Category</label>
        <select id="edit-entry-category" value={category} onChange={(event) => setCategory(event.target.value)}>{categories.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select>
        <label htmlFor="edit-entry-description">Description</label>
        <input id="edit-entry-description" value={description} onChange={(event) => setDescription(event.target.value)} required />
        <label htmlFor="edit-entry-amount">Amount</label>
        <input id="edit-entry-amount" type="number" min="0.01" step="0.01" value={amount} onChange={(event) => setAmount(event.target.value)} required />
        <label htmlFor="edit-entry-date">Date</label>
        <input className="consumer-date-time-control" id="edit-entry-date" type="date" value={spentOn} onChange={(event) => setSpentOn(event.target.value)} required />
        <label htmlFor="edit-entry-note">Note (optional)</label>
        <textarea id="edit-entry-note" value={note} onChange={(event) => setNote(event.target.value)} maxLength={1000} rows={3} />
        {error && <p role="alert">{error}</p>}
        <button type="submit" disabled={saving}>{saving ? "Saving…" : "Save changes"}</button>
        <button type="button" className="budget-destructive-link" onClick={() => setConfirmDelete(true)} disabled={saving}>Delete spending entry</button>
      </form>
    </BottomSheet>
    {confirmDelete && <BottomSheet title="Delete spending entry?" onDismiss={() => !saving && setConfirmDelete(false)}>
      <div className="budget-destructive-sheet"><p>This will remove “{entry.description}” and update entry-based actuals. Manual actuals are unchanged.</p>{error && <p role="alert">{error}</p>}<button type="button" className="budget-destructive-button" onClick={() => void remove()} disabled={saving}>{saving ? "Deleting…" : "Delete spending entry"}</button><button type="button" className="budget-secondary-button" onClick={() => setConfirmDelete(false)} disabled={saving}>Cancel</button></div>
    </BottomSheet>}
  </>;
}
