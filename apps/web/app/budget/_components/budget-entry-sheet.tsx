"use client";

import { FormEvent, useEffect, useState } from "react";
import { api, type BudgetCategory } from "@mykhaya/api-client";
import { BottomSheet } from "@/components/bottom-sheet";

function dateForPeriod(period: { year: number; month: number }) {
  return `${period.year}-${String(period.month).padStart(2, "0")}-01`;
}

export function BudgetEntrySheet({
  homeId,
  initialCategoryId,
  initialSpentOn,
  onClose,
  onSaved,
}: {
  homeId: string;
  initialCategoryId?: string;
  initialSpentOn?: string;
  onClose: () => void;
  onSaved: () => void | Promise<void>;
}) {
  const [categories, setCategories] = useState<BudgetCategory[]>([]);
  const [category, setCategory] = useState(initialCategoryId ?? "");
  const [description, setDescription] = useState("");
  const [amount, setAmount] = useState("");
  const [note, setNote] = useState("");
  const [spentOn, setSpentOn] = useState(initialSpentOn ?? new Date().toISOString().slice(0, 10));
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api.budgetCategories(homeId)
      .then((rows) => {
        setCategories(rows);
        if (!category && rows[0]) setCategory(rows[0].id);
      })
      .catch(() => setError("Couldn’t load categories. Please try again."));
  }, [homeId]);

  async function save(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    setError("");
    try {
      await api.createBudgetEntry(homeId, {
        category_id: category,
        description,
        amount: Number(amount),
        spent_on: spentOn,
        note: note.trim() || null,
      });
      await onSaved();
      onClose();
    } catch {
      setError("Couldn’t save spending entry. Please try again.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <BottomSheet title="Add spending entry" onDismiss={() => !saving && onClose()}>
      <form className="budget-sheet-form" onSubmit={save}>
        <label htmlFor="new-entry-category">Category</label>
        <select id="new-entry-category" value={category} onChange={(event) => setCategory(event.target.value)} required>
          {categories.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
        </select>
        <label htmlFor="new-entry-description">Description</label>
        <input id="new-entry-description" value={description} onChange={(event) => setDescription(event.target.value)} required />
        <label htmlFor="new-entry-amount">Amount</label>
        <input id="new-entry-amount" type="number" min="0.01" step="0.01" value={amount} onChange={(event) => setAmount(event.target.value)} required />
        <label htmlFor="new-entry-date">Date</label>
        <input className="consumer-date-time-control" id="new-entry-date" type="date" value={spentOn} onChange={(event) => setSpentOn(event.target.value)} required />
        <label htmlFor="new-entry-note">Note (optional)</label>
        <textarea id="new-entry-note" value={note} onChange={(event) => setNote(event.target.value)} maxLength={1000} rows={3} />
        {error && <p role="alert">{error}</p>}
        <button type="submit" disabled={saving}>{saving ? "Adding…" : "Add entry"}</button>
      </form>
    </BottomSheet>
  );
}

export function periodDate(period: { year: number; month: number }) {
  return dateForPeriod(period);
}
