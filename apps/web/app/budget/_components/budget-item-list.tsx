"use client";

import { FormEvent, useEffect, useState } from "react";
import { ChevronRight, CircleDollarSign } from "lucide-react";
import { api, type BudgetItem, type BudgetMonthItem } from "@mykhaya/api-client";
import { BottomSheet } from "@/components/bottom-sheet";
import { FormField, FormLayout, FormRow, FormSheet } from "@/components/form-layout";
import { BudgetEntrySheet } from "./budget-entry-sheet";
import { BudgetAmountField, useBudgetFieldErrors } from "./budget-form-fields";

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
  const [saving, setSaving] = useState(false);
  const fields = useBudgetFieldErrors({
    name: { missing: "Enter a name.", blank: "Enter a name." },
    amount: { missing: "Enter an amount." },
    startsOn: { missing: "Choose a start month." },
    endsOn: { range: "Choose an end month on or after the start month." },
  });
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
      fields.clearAll();
    } catch {
      setError("Couldn’t load budget item. Please try again.");
    }
  }

  async function save(event: FormEvent) {
    event.preventDefault();
    if (!editing?.budget_item_id || !master || saving) return;
    if (!fields.check()) {
      setError("");
      return;
    }
    setSaving(true);
    setError("");
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
    } finally {
      setSaving(false);
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

    {editing && <FormSheet
      title={`Edit ${editing.item_type === "fixed" ? "fixed cost" : "variable budget"}`}
      onDismiss={() => setEditing(null)}
      busy={saving}
      primaryAction={<button type="submit" form="budget-item-edit-form" disabled={saving}>{saving ? "Saving…" : "Save changes"}</button>}
    >
      <FormLayout id="budget-item-edit-form" ref={fields.formRef} onSubmit={save}>
        {error && <p className="notice error" role="alert">{error}</p>}
        <FormField label="Name" error={fields.errors.name}>
          {(control) => <input {...control} name="name" value={name} onChange={(event) => { setName(event.target.value); fields.clear("name"); }} required />}
        </FormField>
        <BudgetAmountField label="Planned amount" name="amount" value={amount} onChange={(value) => { setAmount(value); fields.clear("amount"); }} error={fields.errors.amount} />
        {editing.item_type === "fixed" && <>
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
        <button type="button" className="budget-destructive-link" disabled={saving} onClick={() => void archive(editing)}>Archive item</button>
      </FormLayout>
    </FormSheet>}

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
