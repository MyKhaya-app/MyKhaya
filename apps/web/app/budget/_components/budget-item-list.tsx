"use client";

import { FormEvent, useEffect, useState } from "react";
import { ChevronRight, CircleDollarSign } from "lucide-react";
import { api, type BudgetMonthItem } from "@mykhaya/api-client";
import { BottomSheet } from "@/components/bottom-sheet";

export function BudgetItemList({
  homeId,
  categoryId,
  year,
  month,
  onRefresh,
}: {
  homeId: string;
  categoryId: string;
  year: number;
  month: number;
  onRefresh: () => void;
}) {
  const [items, setItems] = useState<BudgetMonthItem[]>([]);
  const [editing, setEditing] = useState<BudgetMonthItem | null>(null);
  const [name, setName] = useState("");
  const [amount, setAmount] = useState("");
  const [error, setError] = useState("");
  const load = () => void api.budgetMonth(homeId, year, month).then((data) => {
    const category = data.categories.find((item) => item.category_id === categoryId);
    setItems(category?.items ?? []);
  }).catch(() => setItems([]));

  useEffect(() => { load(); }, [categoryId, homeId, month, year]);

  function open(item: BudgetMonthItem) {
    setEditing(item);
    setName(item.name);
    setAmount(String(item.planned_amount));
    setError("");
  }

  async function save(event: FormEvent) {
    event.preventDefault();
    if (!editing?.budget_item_id) return;
    try {
      const master = await api.budgetItems(homeId, categoryId).then((rows) => rows.find((row) => row.id === editing.budget_item_id));
      if (!master) throw new Error("Budget item not found");
      await api.updateBudgetItem(homeId, editing.budget_item_id, {
        name: name.trim(),
        default_amount: master.default_amount,
        recurring: master.recurring,
        starts_on: master.starts_on,
        year,
        month,
        planned_amount: Number(amount),
      });
      setEditing(null);
      onRefresh();
      load();
    } catch {
      setError("Couldn’t save budget item. Please try again.");
    }
  }

  async function archive() {
    if (!editing?.budget_item_id) return;
    try {
      await api.deleteBudgetItem(homeId, editing.budget_item_id);
      setEditing(null);
      onRefresh();
      load();
    } catch {
      setError("Couldn’t archive budget item. Please try again.");
    }
  }

  if (!items.length) return null;
  return <>
    <section className="budget-item-detail-list">
      <h2 className="budget-section-title">Planned items</h2>
      <div className="budget-list">
        {items.map((item) => <button type="button" className="budget-list-row" key={item.id} onClick={() => open(item)}>
          <span className="budget-icon"><CircleDollarSign size={20} /></span>
          <span className="budget-row-copy"><strong>{item.name}</strong><small>{item.item_type === "fixed" ? "Fixed" : "Variable"} · {new Intl.NumberFormat("en-GB", { style: "currency", currency: "GBP" }).format(item.planned_amount)}</small></span>
          <ChevronRight size={20} />
        </button>)}
      </div>
    </section>
    {editing && <BottomSheet title={`Edit ${editing.item_type === "fixed" ? "fixed cost" : "variable budget"}`} onDismiss={() => setEditing(null)}>
      <form className="budget-sheet-form" onSubmit={save}>
        <label htmlFor="edit-budget-item-name">Name</label>
        <input id="edit-budget-item-name" value={name} onChange={(event) => setName(event.target.value)} required />
        <label htmlFor="edit-budget-item-amount">Planned amount</label>
        <input id="edit-budget-item-amount" type="number" min="0" step="0.01" value={amount} onChange={(event) => setAmount(event.target.value)} required />
        {error && <p role="alert">{error}</p>}
        <button type="submit">Save changes</button>
        <button type="button" className="budget-destructive-link" onClick={() => void archive()}>Archive item</button>
      </form>
    </BottomSheet>}
  </>;
}
