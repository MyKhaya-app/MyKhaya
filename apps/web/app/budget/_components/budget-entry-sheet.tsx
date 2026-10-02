"use client";

import { FormEvent, useEffect, useState } from "react";
import { api, type BudgetCategory, type BudgetMonthItem } from "@mykhaya/api-client";
import { BottomSheet } from "@/components/bottom-sheet";

function dateForPeriod(period: { year: number; month: number }) {
  return `${period.year}-${String(period.month).padStart(2, "0")}-01`;
}

const currency = new Intl.NumberFormat("en-GB", { style: "currency", currency: "GBP" });

export function BudgetEntrySheet({
  homeId,
  initialCategoryId,
  initialSpentOn,
  initialFixedItem,
  onClose,
  onSaved,
}: {
  homeId: string;
  initialCategoryId?: string;
  initialSpentOn?: string;
  initialFixedItem?: { budgetMonthItemId: string; categoryId: string; description: string; amount: number };
  onClose: () => void;
  onSaved: () => void | Promise<void>;
}) {
  const [categories, setCategories] = useState<BudgetCategory[]>([]);
  const [category, setCategory] = useState(initialFixedItem?.categoryId ?? initialCategoryId ?? "");
  const [description, setDescription] = useState(initialFixedItem?.description ?? "");
  const [amount, setAmount] = useState(initialFixedItem ? String(initialFixedItem.amount) : "");
  const [note, setNote] = useState("");
  const [spentOn, setSpentOn] = useState(initialSpentOn ?? new Date().toISOString().slice(0, 10));
  const [fixedItems, setFixedItems] = useState<BudgetMonthItem[]>([]);
  const [fixedItemId, setFixedItemId] = useState(initialFixedItem?.budgetMonthItemId ?? "");
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

  useEffect(() => {
    if (!category || !spentOn) {
      setFixedItems([]);
      return;
    }
    const [yearPart, monthPart] = spentOn.split("-");
    const year = Number(yearPart);
    const month = Number(monthPart);
    if (!year || !month) {
      setFixedItems([]);
      return;
    }
    api.budgetMonth(homeId, year, month)
      .then((data) => {
        const items = (data.categories.find((row) => row.category_id === category)?.items ?? [])
          .filter((item) => item.item_type === "fixed")
          .sort((a, b) => (a.payment_status === b.payment_status ? 0 : a.payment_status === "paid" ? 1 : -1));
        setFixedItems(items);
      })
      .catch(() => setFixedItems([]));
  }, [homeId, category, spentOn]);

  function selectFixedItem(id: string) {
    setFixedItemId(id);
    const item = fixedItems.find((row) => row.id === id);
    if (item) {
      setDescription(item.name);
      setAmount(String(item.planned_amount));
    }
  }

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
        budget_month_item_id: fixedItemId || null,
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
        <select id="new-entry-category" value={category} onChange={(event) => { setCategory(event.target.value); setFixedItemId(""); }} required>
          {categories.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
        </select>
        {fixedItems.length > 0 && <>
          <label htmlFor="new-entry-fixed-item">Fixed item (optional)</label>
          <select id="new-entry-fixed-item" value={fixedItemId} onChange={(event) => selectFixedItem(event.target.value)}>
            <option value="">None</option>
            {fixedItems.map((item) => (
              <option key={item.id} value={item.id}>
                {item.name} · {currency.format(item.planned_amount)} · {item.payment_status === "paid" ? "Paid" : "Not paid"}
              </option>
            ))}
          </select>
        </>}
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
