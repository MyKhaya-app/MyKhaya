"use client";

import { FormEvent, useEffect, useState } from "react";
import { api, type BudgetCategory, type BudgetMonthItem } from "@mykhaya/api-client";
import { FormField, FormLayout, FormRow, FormSheet } from "@/components/form-layout";
import { BudgetAmountField, useBudgetFieldErrors, type BudgetFieldMessages } from "./budget-form-fields";

/** Field wording shared by the Add and Edit spending entry sheets. */
export const ENTRY_FIELD_MESSAGES: BudgetFieldMessages = {
  category: { missing: "Choose a category." },
  description: { missing: "Enter a description." },
  amount: { missing: "Enter an amount." },
  spentOn: { missing: "Choose a date." },
};

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
  const fields = useBudgetFieldErrors(ENTRY_FIELD_MESSAGES);

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
    if (saving) return;
    if (!fields.check()) {
      setError("");
      return;
    }
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
    <FormSheet
      title="Add spending entry"
      onDismiss={onClose}
      busy={saving}
      primaryAction={<button type="submit" form="budget-entry-form" disabled={saving}>{saving ? "Adding…" : "Add entry"}</button>}
    >
      <FormLayout id="budget-entry-form" ref={fields.formRef} onSubmit={save}>
        {error && <p className="notice error" role="alert">{error}</p>}
        <FormField label="Category" error={fields.errors.category}>
          {(control) => (
            <select {...control} name="category" value={category} onChange={(event) => { setCategory(event.target.value); setFixedItemId(""); fields.clear("category"); }} required>
              {categories.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
            </select>
          )}
        </FormField>
        {fixedItems.length > 0 && <FormField label="Fixed item (optional)">
          {(control) => (
            <select {...control} value={fixedItemId} onChange={(event) => selectFixedItem(event.target.value)}>
              <option value="">None</option>
              {fixedItems.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name} · {currency.format(item.planned_amount)} · {item.payment_status === "paid" ? "Paid" : "Not paid"}
                </option>
              ))}
            </select>
          )}
        </FormField>}
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
      </FormLayout>
    </FormSheet>
  );
}

export function periodDate(period: { year: number; month: number }) {
  return dateForPeriod(period);
}
