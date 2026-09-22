"use client";

import { FormEvent, useEffect, useState } from "react";
import { ArrowRight, CircleDollarSign, Plus, Receipt, WalletCards } from "lucide-react";
import { api, type BudgetCategory } from "@mykhaya/api-client";
import { BottomSheet } from "@/components/bottom-sheet";

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
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const period = currentPeriod();

  useEffect(() => {
    if (mode !== "fixed" && mode !== "variable") return;
    api.budgetCategories(homeId).then((rows) => {
      setCategories(rows);
      if (!categoryId && rows[0]) setCategoryId(rows[0].id);
    }).catch(() => setError("Couldn’t load categories. Please try again."));
  }, [categoryId, homeId, mode]);

  function open(next: AddMode) {
    setError("");
    setMode(next);
  }

  function close() {
    if (!saving) setMode(null);
  }

  async function save(event: FormEvent) {
    event.preventDefault();
    if (mode !== "fixed" && mode !== "variable") return;
    setSaving(true);
    setError("");
    try {
      await api.createBudgetItem(homeId, {
        category_id: categoryId,
        name: name.trim() || categories.find((item) => item.id === categoryId)?.name || "Budget item",
        item_type: mode,
        default_amount: Number(amount),
        recurring: mode === "fixed" ? recurring : recurring,
        starts_on: `${period.year}-${String(period.month).padStart(2, "0")}-01`,
        year: period.year,
        month: period.month,
      });
      onRefresh();
      setMode(null);
      setName("");
      setAmount("");
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
    {(mode === "fixed" || mode === "variable") && <BottomSheet title={mode === "fixed" ? "Add fixed cost" : "Add variable budget"} onDismiss={close}>
      <form className="budget-sheet-form" onSubmit={save}>
        <label htmlFor="budget-item-category">Category</label>
        <select id="budget-item-category" value={categoryId} onChange={(event) => setCategoryId(event.target.value)} required>{categories.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select>
        <label htmlFor="budget-item-name">Name</label>
        <input id="budget-item-name" value={name} onChange={(event) => setName(event.target.value)} placeholder={mode === "fixed" ? "e.g. Mortgage" : "Optional"} />
        <label htmlFor="budget-item-amount">{mode === "fixed" ? "Monthly amount" : "Planned amount"}</label>
        <input id="budget-item-amount" type="number" min="0" step="0.01" value={amount} onChange={(event) => setAmount(event.target.value)} required />
        <label className="budget-sheet-toggle"><span><strong>{mode === "fixed" ? "Repeat monthly" : "Carry forward automatically"}</strong></span><input type="checkbox" checked={recurring} onChange={(event) => setRecurring(event.target.checked)} /></label>
        {error && <p role="alert">{error}</p>}
        <button type="submit" disabled={saving}>{saving ? "Saving…" : mode === "fixed" ? "Add fixed cost" : "Add variable budget"}</button>
      </form>
    </BottomSheet>}
  </>;
}
