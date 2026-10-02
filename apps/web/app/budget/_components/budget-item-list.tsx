"use client";

import { FormEvent, useEffect, useState } from "react";
import { ChevronRight, CircleDollarSign } from "lucide-react";
import { api, type BudgetItem, type BudgetMonthItem } from "@mykhaya/api-client";
import { BottomSheet } from "@/components/bottom-sheet";
import { BudgetEntrySheet } from "./budget-entry-sheet";

const currency = new Intl.NumberFormat("en-GB", { style: "currency", currency: "GBP" });

function monthLabel(value?: string | null) {
  if (!value) return "No end date";
  const [yearPart, monthPart] = value.split("-");
  return new Date(Number(yearPart), Number(monthPart) - 1, 1).toLocaleDateString("en-GB", { month: "long", year: "numeric" });
}

function toMonthInput(value?: string | null) {
  return value ? value.slice(0, 7) : "";
}

/** Today's date when paying the item for the month currently in view;
 * otherwise the 1st of that month, so the linked entry always lands in the
 * same BudgetMonthItem's month (the server rejects a cross-month link). */
function paymentDateFor(year: number, month: number) {
  const today = new Date();
  if (today.getFullYear() === year && today.getMonth() + 1 === month) {
    return today.toISOString().slice(0, 10);
  }
  return `${year}-${String(month).padStart(2, "0")}-01`;
}

export function BudgetItemList({
  homeId,
  categoryId,
  year,
  month,
  onRefresh,
  onViewTransaction,
}: {
  homeId: string;
  categoryId: string;
  year: number;
  month: number;
  onRefresh: () => void;
  onViewTransaction?: (entryId: string) => void;
}) {
  const [items, setItems] = useState<BudgetMonthItem[]>([]);
  const [detailItem, setDetailItem] = useState<BudgetMonthItem | null>(null);
  const [editing, setEditing] = useState<BudgetMonthItem | null>(null);
  const [master, setMaster] = useState<BudgetItem | null>(null);
  const [name, setName] = useState("");
  const [amount, setAmount] = useState("");
  const [startsOn, setStartsOn] = useState("");
  const [endsOn, setEndsOn] = useState("");
  const [notes, setNotes] = useState("");
  const [error, setError] = useState("");
  const [payingItem, setPayingItem] = useState<BudgetMonthItem | null>(null);
  const load = () => void api.budgetMonth(homeId, year, month).then((data) => {
    const category = data.categories.find((item) => item.category_id === categoryId);
    setItems(category?.items ?? []);
    setDetailItem((current) => (current ? category?.items.find((item) => item.id === current.id) ?? null : null));
  }).catch(() => setItems([]));

  useEffect(() => { load(); }, [categoryId, homeId, month, year]);

  function openDetail(item: BudgetMonthItem) {
    setDetailItem(item);
    setError("");
  }

  async function openEdit(item: BudgetMonthItem) {
    if (!item.budget_item_id) return;
    try {
      const masterItem = await api.budgetItems(homeId, categoryId).then((rows) => rows.find((row) => row.id === item.budget_item_id));
      if (!masterItem) throw new Error("Budget item not found");
      setMaster(masterItem);
      setEditing(item);
      setDetailItem(null);
      setName(item.name);
      setAmount(String(item.planned_amount));
      setStartsOn(toMonthInput(masterItem.starts_on));
      setEndsOn(toMonthInput(masterItem.ends_on));
      setNotes(masterItem.notes ?? "");
      setError("");
    } catch {
      setError("Couldn’t load budget item. Please try again.");
    }
  }

  async function save(event: FormEvent) {
    event.preventDefault();
    if (!editing?.budget_item_id || !master) return;
    try {
      await api.updateBudgetItem(homeId, editing.budget_item_id, {
        name: name.trim(),
        default_amount: master.default_amount,
        recurring: master.recurring,
        starts_on: `${startsOn}-01`,
        ends_on: endsOn ? `${endsOn}-01` : null,
        notes: notes.trim() || null,
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

  async function archive(item: BudgetMonthItem) {
    if (!item.budget_item_id) return;
    try {
      await api.deleteBudgetItem(homeId, item.budget_item_id);
      setEditing(null);
      setDetailItem(null);
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
        {items.map((item) => <button type="button" className="budget-list-row" key={item.id} onClick={() => openDetail(item)}>
          <span className="budget-icon"><CircleDollarSign size={20} /></span>
          <span className="budget-row-copy"><strong>{item.name}</strong><small>{item.item_type === "fixed" ? "Fixed" : "Variable"} · {currency.format(item.planned_amount)}</small></span>
          {item.item_type === "fixed" && item.payment_status && (
            <span className={`budget-status-pill budget-status-pill-${item.payment_status === "paid" ? "paid" : "notpaid"}`}>
              {item.payment_status === "paid" ? "PAID" : "NOT PAID"}
            </span>
          )}
          <ChevronRight size={20} />
        </button>)}
      </div>
    </section>

    {detailItem && <BottomSheet title={detailItem.name} onDismiss={() => setDetailItem(null)}>
      <div className="budget-item-detail">
        <div className="budget-item-detail-headline">
          <span><strong>{currency.format(detailItem.planned_amount)} / month</strong><small>{detailItem.item_type === "fixed" ? "Fixed monthly amount" : "Variable budget"}</small></span>
          {detailItem.item_type === "fixed" && detailItem.payment_status && (
            <span className={`budget-status-pill budget-status-pill-${detailItem.payment_status === "paid" ? "paid" : "notpaid"}`}>
              {detailItem.payment_status === "paid" ? "PAID" : "NOT PAID"}
            </span>
          )}
        </div>
        {detailItem.item_type === "fixed" && detailItem.payment_status === "paid" && detailItem.paid_entry && (
          <p className="budget-item-detail-row"><span>Last paid</span><strong>{new Date(detailItem.paid_entry.spent_on).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" })} · {currency.format(detailItem.paid_entry.amount)}</strong></p>
        )}
        {detailItem.item_type === "fixed" && (
          <>
            <p className="budget-item-detail-row"><span>Due date</span><strong>1st of each month</strong></p>
            <p className="budget-item-detail-row"><span>Start</span><strong>{monthLabel(detailItem.starts_on)}</strong></p>
            <p className="budget-item-detail-row"><span>End</span><strong>{monthLabel(detailItem.ends_on)}</strong></p>
          </>
        )}
        {detailItem.note && <p className="budget-item-detail-row"><span>Notes</span><strong>{detailItem.note}</strong></p>}
        {error && <p role="alert">{error}</p>}
        <div className="budget-item-detail-actions">
          {detailItem.item_type === "fixed" && detailItem.payment_status !== "paid" && (
            <button type="button" onClick={() => { setPayingItem(detailItem); setDetailItem(null); }}>Mark as paid</button>
          )}
          {detailItem.item_type === "fixed" && detailItem.payment_status === "paid" && detailItem.paid_entry && (
            <button type="button" className="budget-action-row" onClick={() => onViewTransaction?.(detailItem.paid_entry!.id)}>View transaction</button>
          )}
          <button type="button" className="budget-action-row" onClick={() => void openEdit(detailItem)}>Edit item</button>
          <button type="button" className="budget-action-row budget-destructive-link" onClick={() => void archive(detailItem)}>Archive item</button>
        </div>
      </div>
    </BottomSheet>}

    {editing && <BottomSheet title={`Edit ${editing.item_type === "fixed" ? "fixed cost" : "variable budget"}`} onDismiss={() => setEditing(null)}>
      <form className="budget-sheet-form" onSubmit={save}>
        <label htmlFor="edit-budget-item-name">Name</label>
        <input id="edit-budget-item-name" value={name} onChange={(event) => setName(event.target.value)} required />
        <label htmlFor="edit-budget-item-amount">Planned amount</label>
        <input id="edit-budget-item-amount" type="number" min="0" step="0.01" value={amount} onChange={(event) => setAmount(event.target.value)} required />
        {editing.item_type === "fixed" && <>
          <label htmlFor="edit-budget-item-starts-on">Start month</label>
          <input id="edit-budget-item-starts-on" type="month" className="consumer-date-time-control" value={startsOn} onChange={(event) => setStartsOn(event.target.value)} required />
          <label htmlFor="edit-budget-item-ends-on">End month</label>
          <input id="edit-budget-item-ends-on" type="month" className="consumer-date-time-control" value={endsOn} min={startsOn || undefined} onChange={(event) => setEndsOn(event.target.value)} />
          <p className="budget-field-hint">Leave empty for no end date</p>
          <label htmlFor="edit-budget-item-notes">Notes (optional)</label>
          <textarea id="edit-budget-item-notes" value={notes} onChange={(event) => setNotes(event.target.value)} rows={3} />
        </>}
        {error && <p role="alert">{error}</p>}
        <button type="submit">Save changes</button>
        <button type="button" className="budget-destructive-link" onClick={() => void archive(editing)}>Archive item</button>
      </form>
    </BottomSheet>}

    {payingItem && (
      <BudgetEntrySheet
        homeId={homeId}
        initialSpentOn={paymentDateFor(year, month)}
        initialFixedItem={{
          budgetMonthItemId: payingItem.id,
          categoryId: payingItem.category_id,
          description: payingItem.name,
          amount: payingItem.planned_amount,
        }}
        onClose={() => setPayingItem(null)}
        onSaved={async () => { onRefresh(); load(); }}
      />
    )}
  </>;
}
