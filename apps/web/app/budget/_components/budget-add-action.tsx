"use client";

import { FormEvent, useEffect, useState } from "react";
import { ArrowRight, CircleDollarSign, Plus, Receipt, WalletCards } from "lucide-react";
import { api, type BudgetCategory } from "@mykhaya/api-client";
import { BottomSheet } from "@/components/bottom-sheet";
import { FormField, FormLayout, FormRow, FormSheet } from "@/components/form-layout";
import { BudgetAmountField, useBudgetFieldErrors } from "./budget-form-fields";

type AddMode = "menu" | "fixed" | "variable";

function currentPeriod() {
  const now = new Date();
  return { year: now.getFullYear(), month: now.getMonth() + 1 };
}

export function BudgetAddAction({ homeId, onRefresh, onSpending, onIncome }: { homeId: string; onRefresh: () => void; onSpending?: () => void; onIncome?: () => void }) {
  const [mode, setMode] = useState<AddMode | null>(null);
  const [categories, setCategories] = useState<BudgetCategory[]>([]);
  const [categoryId, setCategoryId] = useState("");
  const [name, setName] = useState("");
  const [amount, setAmount] = useState("");
  const [recurring, setRecurring] = useState(true);
  const [startsOn, setStartsOn] = useState("");
  const [endsOn, setEndsOn] = useState("");
  const [notes, setNotes] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const period = currentPeriod();
  const fields = useBudgetFieldErrors({
    category: { missing: "Choose a category." },
    amount: { missing: "Enter an amount." },
    startsOn: { missing: "Choose a start month." },
    endsOn: { range: "Choose an end month on or after the start month." },
  });

  useEffect(() => {
    if (mode !== "fixed" && mode !== "variable") return;
    api.budgetCategories(homeId).then((rows) => {
      setCategories(rows);
      if (!categoryId && rows[0]) setCategoryId(rows[0].id);
    }).catch(() => setError("Couldn’t load categories. Please try again."));
  }, [categoryId, homeId, mode]);

  function open(next: AddMode) {
    setError("");
    fields.clearAll();
    setMode(next);
    setStartsOn(`${period.year}-${String(period.month).padStart(2, "0")}`);
    setEndsOn("");
    setNotes("");
  }

  function close() {
    if (!saving) setMode(null);
  }

  async function save(event: FormEvent) {
    event.preventDefault();
    if ((mode !== "fixed" && mode !== "variable") || saving) return;
    if (!fields.check()) {
      setError("");
      return;
    }
    setSaving(true);
    setError("");
    try {
      await api.createBudgetItem(homeId, {
        category_id: categoryId,
        name: name.trim() || categories.find((item) => item.id === categoryId)?.name || "Budget item",
        item_type: mode,
        default_amount: Number(amount),
        recurring,
        starts_on: `${startsOn || `${period.year}-${String(period.month).padStart(2, "0")}`}-01`,
        ends_on: mode === "fixed" && endsOn ? `${endsOn}-01` : null,
        notes: mode === "fixed" && notes.trim() ? notes.trim() : null,
        year: period.year,
        month: period.month,
      });
      onRefresh();
      setMode(null);
      setName("");
      setAmount("");
      setEndsOn("");
      setNotes("");
    } catch {
      setError("Couldn’t save budget item. Please try again.");
    } finally {
      setSaving(false);
    }
  }

  return <>
    <button type="button" className="rr-fab" aria-label="Add Budget item" onClick={() => open("menu")}>
      <Plus size={22} aria-hidden="true" />
      <span aria-hidden="true">Add</span>
    </button>
    {mode === "menu" && <BottomSheet title="What would you like to add?" onDismiss={close}>
      <div className="budget-picker-list budget-add-picker-list">
        <button type="button" className="budget-picker-row" onClick={() => open("fixed")}><span className="budget-picker-icon"><WalletCards size={21} /></span><span className="budget-picker-copy"><strong>Fixed monthly cost</strong><small>Mortgage, broadband, subscriptions, etc.</small></span><ArrowRight size={19} aria-hidden="true" /></button>
        <button type="button" className="budget-picker-row" onClick={() => open("variable")}><span className="budget-picker-icon"><CircleDollarSign size={21} /></span><span className="budget-picker-copy"><strong>Variable budget</strong><small>Groceries, fuel, eating out, etc.</small></span><ArrowRight size={19} aria-hidden="true" /></button>
        <button type="button" className="budget-picker-row" onClick={() => { setMode(null); onSpending?.(); }}><span className="budget-picker-icon"><Receipt size={21} /></span><span className="budget-picker-copy"><strong>Spending entry</strong><small>Record money you have spent.</small></span><ArrowRight size={19} aria-hidden="true" /></button>
        <button type="button" className="budget-picker-row" onClick={() => { setMode(null); onIncome?.(); }}><span className="budget-picker-icon"><WalletCards size={21} /></span><span className="budget-picker-copy"><strong>Income</strong><small>Add or update income.</small></span><ArrowRight size={19} aria-hidden="true" /></button>
      </div>
    </BottomSheet>}
    {(mode === "fixed" || mode === "variable") && <FormSheet
      title={mode === "fixed" ? "Add fixed cost" : "Add variable budget"}
      onDismiss={close}
      busy={saving}
      primaryAction={<button type="submit" form="budget-item-form" disabled={saving}>{saving ? "Saving…" : mode === "fixed" ? "Add fixed cost" : "Add variable budget"}</button>}
    >
      <FormLayout id="budget-item-form" ref={fields.formRef} onSubmit={save}>
        {error && <p className="notice error" role="alert">{error}</p>}
        <FormField label="Category" error={fields.errors.category}>
          {(control) => <select {...control} name="category" value={categoryId} onChange={(event) => { setCategoryId(event.target.value); fields.clear("category"); }} required>{categories.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select>}
        </FormField>
        <FormField label="Name">
          {(control) => <input {...control} value={name} onChange={(event) => setName(event.target.value)} placeholder={mode === "fixed" ? "e.g. Mortgage" : "Optional"} />}
        </FormField>
        <BudgetAmountField label={mode === "fixed" ? "Monthly amount" : "Planned amount"} name="amount" value={amount} onChange={(value) => { setAmount(value); fields.clear("amount"); }} error={fields.errors.amount} />
        <label className="budget-sheet-toggle"><span><strong>{mode === "fixed" ? "Repeat monthly" : "Carry forward automatically"}</strong></span><input type="checkbox" checked={recurring} onChange={(event) => setRecurring(event.target.checked)} /></label>
        {mode === "fixed" && <>
          <FormRow minColumnWidth="10rem">
            <FormField label="Start month" error={fields.errors.startsOn}>
              {(control) => <input {...control} name="startsOn" type="month" value={startsOn} onChange={(event) => { setStartsOn(event.target.value); fields.clear("startsOn"); fields.clear("endsOn"); }} required />}
            </FormField>
            <FormField label="End month" hint="Leave empty for no end date" error={fields.errors.endsOn}>
              {(control) => <input {...control} name="endsOn" type="month" value={endsOn} min={startsOn || undefined} onChange={(event) => { setEndsOn(event.target.value); fields.clear("endsOn"); }} />}
            </FormField>
          </FormRow>
          <FormField label="Notes (optional)">
            {(control) => <textarea {...control} value={notes} onChange={(event) => setNotes(event.target.value)} rows={3} />}
          </FormField>
        </>}
      </FormLayout>
    </FormSheet>}
  </>;
}
