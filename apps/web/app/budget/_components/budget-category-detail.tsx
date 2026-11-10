"use client";

import { FormEvent, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { BarChart3, ChevronDown, ChevronLeft, ChevronRight, CircleDollarSign, ShoppingCart, WalletCards } from "lucide-react";
import { ApiError, api, type BudgetCategory, type BudgetMonth, type BudgetSpendingEntry } from "@mykhaya/api-client";
import { FormField, FormLayout, FormSheet } from "@/components/form-layout";
import { BudgetAddAction } from "./budget-add-action";
import { BudgetEntrySheet, periodDate } from "./budget-entry-sheet";
import { BudgetEditEntrySheet } from "./budget-edit-entry-sheet";
import { BudgetAmountField, useBudgetFieldErrors } from "./budget-form-fields";
import { BudgetItemList } from "./budget-item-list";
import { BudgetTabs } from "./budget-tabs";

const money = (value: number) => new Intl.NumberFormat("en-GB", { style: "currency", currency: "GBP", maximumFractionDigits: 2 }).format(value);
const periodNow = () => { const now = new Date(); return { year: now.getFullYear(), month: now.getMonth() + 1 }; };
const monthLabel = (year: number, month: number) => new Intl.DateTimeFormat("en-GB", { month: "long", year: "numeric" }).format(new Date(year, month - 1, 1));

function Period({ year, month, onChange }: { year: number; month: number; onChange: (year: number, month: number) => void }) {
  const move = (delta: number) => { const next = new Date(year, month - 1 + delta, 1); onChange(next.getFullYear(), next.getMonth() + 1); };
  return <div className="budget-period-control"><button type="button" aria-label="Previous month" onClick={() => move(-1)}><ChevronLeft size={21} /></button><strong>{monthLabel(year, month)}</strong><button type="button" aria-label="Next month" onClick={() => move(1)}><ChevronRight size={21} /></button></div>;
}

function Stat({ label, value, icon: Icon }: { label: string; value: string; icon: typeof WalletCards }) {
  return <div className="budget-stat-card"><span className="budget-icon"><Icon size={21} /></span><span><small>{label}</small><strong>{value}</strong></span></div>;
}

function NotesAction({ homeId, categoryId, year, month }: { homeId: string; categoryId: string; year: number; month: number }) {
  const [note, setNote] = useState("");
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => { void api.budgetMonth(homeId, year, month).then((data) => setNote(data.categories.find((item) => item.category_id === categoryId)?.note ?? "")); }, [categoryId, homeId, month, year]);
  async function save(event: FormEvent) {
    event.preventDefault();
    if (saving) return;
    setSaving(true);
    setError("");
    try {
      await api.updateBudgetCategoryNote(homeId, year, month, categoryId, note);
      setOpen(false);
    } catch {
      setError("Couldn’t save note. Please try again.");
    } finally {
      setSaving(false);
    }
  }
  return <>
    <button type="button" className="budget-action-row" onClick={() => { setError(""); setOpen(true); }}><span className="budget-icon"><WalletCards size={20} /></span><strong>Budget notes</strong><ChevronRight size={20} /></button>
    {open && <FormSheet title="Budget notes" onDismiss={() => setOpen(false)} busy={saving} primaryAction={<button type="submit" form="budget-note-form" disabled={saving}>{saving ? "Saving…" : "Save note"}</button>}>
      <FormLayout id="budget-note-form" onSubmit={save}>
        {error && <p className="notice error" role="alert">{error}</p>}
        <FormField label="Optional note">
          {(control) => <textarea {...control} value={note} onChange={(event) => setNote(event.target.value)} maxLength={1000} rows={5} placeholder="Add a note for this category" />}
        </FormField>
      </FormLayout>
    </FormSheet>}
  </>;
}

/**
 * Update actual amount: the category's own monthly amount, which the API
 * adds to its spending entries. The sheet owns one draft, started from the
 * stored value (fixed_actual, else a legacy row's manual_actual, else 0) and
 * changed only by typing, so a re-render cannot reset what was typed.
 * Saving a legacy row's manual_actual unchanged is a no-op in the API; the
 * entries total is never offered as the starting value, because saving it
 * would count those entries twice.
 */
function ActualSheet({ homeId, categoryId, year, month, initial, additive, onClose, onSaved }: { homeId: string; categoryId: string; year: number; month: number; initial: string; additive: boolean; onClose: () => void; onSaved: () => Promise<void> }) {
  const [actual, setActual] = useState(initial);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const fields = useBudgetFieldErrors({ actual: { missing: "Enter an amount." } });
  const label = additive ? "Fixed monthly amount" : "Actual amount";
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
      await api.updateBudgetActual(homeId, year, month, categoryId, { source: "manual", manual_actual: Number(actual) });
      await onSaved();
      onClose();
    } catch {
      setError("Couldn’t save the amount. Please try again.");
    } finally {
      setSaving(false);
    }
  }
  return <FormSheet title={additive ? "Update fixed monthly amount" : "Update actual amount"} onDismiss={onClose} busy={saving} primaryAction={<button type="submit" form="budget-actual-form" disabled={saving}>{saving ? "Saving…" : additive ? "Save fixed amount" : "Save actual"}</button>}>
    <FormLayout id="budget-actual-form" ref={fields.formRef} onSubmit={save}>
      {error && <p className="notice error" role="alert">{error}</p>}
      <BudgetAmountField label={label} name="actual" value={actual} onChange={(value) => { setActual(value); fields.clear("actual"); }} error={fields.errors.actual} />
    </FormLayout>
  </FormSheet>;
}

/** Edit planned amount: the category's plan for the month in view. */
function PlanSheet({ homeId, categoryId, year, month, initial, onClose, onSaved }: { homeId: string; categoryId: string; year: number; month: number; initial: string; onClose: () => void; onSaved: () => void }) {
  const [planned, setPlanned] = useState(initial);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const fields = useBudgetFieldErrors({ planned: { missing: "Enter the planned amount." } });
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
      await api.updateBudgetPlan(homeId, year, month, categoryId, Number(planned));
      onSaved();
      onClose();
    } catch {
      setError("Couldn’t save planned amount. Please try again.");
    } finally {
      setSaving(false);
    }
  }
  return <FormSheet title="Edit planned amount" onDismiss={onClose} busy={saving} primaryAction={<button type="submit" form="budget-plan-form" disabled={saving}>{saving ? "Saving…" : "Save plan"}</button>}>
    <FormLayout id="budget-plan-form" ref={fields.formRef} onSubmit={save}>
      {error && <p className="notice error" role="alert">{error}</p>}
      <BudgetAmountField label="Planned amount (per month)" name="planned" value={planned} onChange={(value) => { setPlanned(value); fields.clear("planned"); }} error={fields.errors.planned} />
    </FormLayout>
  </FormSheet>;
}

export function BudgetCategoryDetail({ homeId, categoryId }: { homeId: string; categoryId: string }) {
  const params = useSearchParams();
  const router = useRouter();
  const [period, setPeriod] = useState(() => ({
    year: Number(params.get("year")) || periodNow().year,
    month: Number(params.get("month")) || periodNow().month,
  }));
  const [month, setMonth] = useState<BudgetMonth | null>(null);
  const [category, setCategory] = useState<BudgetCategory | null>(null);
  const [entries, setEntries] = useState<BudgetSpendingEntry[]>([]);
  const [sheet, setSheet] = useState<"plan" | "actual" | null>(null);
  const [quickOpen, setQuickOpen] = useState(false);
  const [planned, setPlanned] = useState("0");
  const [entryOpen, setEntryOpen] = useState(false);
  const [selectedEntry, setSelectedEntry] = useState<BudgetSpendingEntry | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [loading, setLoading] = useState(true);
  const [missing, setMissing] = useState(false);
  const [error, setError] = useState("");

  const reload = async () => {
    setLoading(true);
    setMissing(false);
    setError("");
    try {
      const [categories, nextMonth] = await Promise.all([
        api.budgetCategories(homeId),
        api.budgetMonth(homeId, period.year, period.month),
      ]);
      setCategory(categories.find((item) => item.id === categoryId) ?? null);
      setMonth(nextMonth);
      if (nextMonth.configured === false) {
        setEntries([]);
        setMissing(true);
        return;
      }
      const nextEntries = await api.budgetEntries(homeId, period);
      setEntries(nextEntries.filter((entry) => entry.category_id === categoryId).sort((a, b) => b.spent_on.localeCompare(a.spent_on) || b.id.localeCompare(a.id)));
      const row = nextMonth.categories.find((item) => item.category_id === categoryId);
      if (row) setPlanned(String(row.planned_amount));
    } catch (cause) {
      setMonth(null);
      setEntries([]);
      if (cause instanceof ApiError && cause.status === 404) setMissing(true);
      else setError("That Budget period could not be loaded.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { void reload(); }, [categoryId, homeId, period.month, period.year, refreshKey]);

  async function viewTransaction(entryId: string) {
    const found = entries.find((entry) => entry.id === entryId);
    if (found) { setSelectedEntry(found); return; }
    try {
      setSelectedEntry(await api.budgetEntry(homeId, entryId));
    } catch {
      // No feedback surface for this edge case; the sheet simply stays closed.
    }
  }

  const row = month?.categories.find((item) => item.category_id === categoryId);
  function changePeriod(year: number, month: number) {
    setPeriod({ year, month });
    router.replace(`/budget/categories/${categoryId}?year=${year}&month=${month}`);
  }
  const header = <><section className="budget-hero"><div><p className="budget-eyebrow">Budget</p><h1>{category?.name ?? "Category"}</h1><p>Optional spending detail sits under your plan.</p></div><div className="budget-artwork" aria-hidden="true"><img src="/images/PiggyBank_Budget_Image.png" alt="" /></div></section><BudgetTabs /><Period {...period} onChange={changePeriod} /></>;
  if (loading) return <>{header}<p role="status">Loading category details…</p></>;
  if (error) return <>{header}<div className="budget-empty-state"><p role="alert">{error}</p><button type="button" onClick={() => void reload()}>Try again</button></div></>;
  if (missing) return <>{header}<div className="budget-empty-state"><h2>{monthLabel(period.year, period.month)}</h2><p>This Budget period has not been set up yet.</p><button type="button" onClick={() => void api.createBudgetMonth(homeId, period.year, period.month).then(reload).catch(() => setError("That Budget period could not be created."))}>Set up this period</button></div></>;
  if (!row) return <>{header}<div className="budget-empty-state"><h2>{category?.name ?? "Category"}</h2><p>This category is not included in the selected Budget period.</p></div></>;
  const remaining = row.planned_amount - row.actual_amount;
  const usage = Math.min((row.actual_amount / Math.max(row.planned_amount, 1)) * 100, 100);
  const isAdditiveActual = row.fixed_actual !== null;
  return <>
    <section className="budget-hero"><div><p className="budget-eyebrow">Budget</p><h1>{row.category_name}</h1><p>Optional spending detail sits under your plan.</p></div><div className="budget-artwork" aria-hidden="true"><img src="/images/PiggyBank_Budget_Image.png" alt="" /></div></section>
    <BudgetTabs />
    <Period {...period} onChange={changePeriod} />
    <section className="budget-detail-stats"><Stat label="Planned" value={money(row.planned_amount)} icon={CircleDollarSign} /><Stat label="Actual" value={money(row.actual_amount)} icon={BarChart3} /><Stat label="Remaining" value={money(remaining)} icon={CircleDollarSign} /></section>
    <div className="budget-usage-card"><strong>{row.actual_amount > 0 ? `${Math.round(usage)}% used` : "No spending yet"}</strong><span className="budget-progress"><span style={{ width: `${usage}%` }} /></span></div>
    <button type="button" className="budget-quick-actions-toggle" aria-expanded={quickOpen} onClick={() => setQuickOpen((open) => !open)}><strong>Quick actions</strong><ChevronDown size={20} aria-hidden="true" /></button>
    {quickOpen && <div className="budget-list budget-quick-actions"><button type="button" className="budget-action-row" onClick={() => setSheet("plan")}><span className="budget-icon"><CircleDollarSign size={20} /></span><strong>Edit planned amount</strong><ChevronRight size={20} /></button><button type="button" className="budget-action-row" onClick={() => setSheet("actual")}><span className="budget-icon"><BarChart3 size={20} /></span><strong>Update actual amount</strong><ChevronRight size={20} /></button><button type="button" className="budget-action-row" onClick={() => setEntryOpen(true)}><span className="budget-icon"><ShoppingCart size={20} /></span><strong>Add spending entry</strong><ChevronRight size={20} /></button><NotesAction homeId={homeId} categoryId={categoryId} year={period.year} month={period.month} /></div>}
    <section className="budget-transactions" aria-labelledby="budget-transactions-heading"><h2 id="budget-transactions-heading" className="budget-section-title">Transactions</h2>{entries.length ? <div className="budget-list">{entries.map((entry) => <button type="button" className="budget-transaction-row" key={entry.id} onClick={() => setSelectedEntry(entry)} aria-label={`Edit transaction ${entry.description}`}><span className="budget-icon"><ShoppingCart size={19} /></span><span className="budget-row-copy"><strong>{entry.description}</strong><small>{entry.spent_on}</small></span><strong>{money(entry.amount)}</strong></button>)}</div> : <p className="budget-note">No spending recorded yet</p>}</section>
    <BudgetItemList key={refreshKey} homeId={homeId} categoryId={categoryId} year={period.year} month={period.month} onRefresh={() => setRefreshKey((value) => value + 1)} onViewTransaction={viewTransaction} />
    <BudgetAddAction homeId={homeId} onRefresh={() => setRefreshKey((value) => value + 1)} onSpending={() => setEntryOpen(true)} />
    {entryOpen && <BudgetEntrySheet homeId={homeId} initialCategoryId={categoryId} initialSpentOn={periodDate(period)} onClose={() => setEntryOpen(false)} onSaved={reload} />}
    {sheet === "plan" && <PlanSheet homeId={homeId} categoryId={categoryId} year={period.year} month={period.month} initial={planned} onClose={() => setSheet(null)} onSaved={() => void reload()} />}
    {sheet === "actual" && <ActualSheet homeId={homeId} categoryId={categoryId} year={period.year} month={period.month} initial={String(row.fixed_actual ?? row.manual_actual ?? 0)} additive={isAdditiveActual} onClose={() => setSheet(null)} onSaved={reload} />}
    {selectedEntry && <BudgetEditEntrySheet homeId={homeId} entry={selectedEntry} onClose={() => setSelectedEntry(null)} onSaved={reload} />}
  </>;
}
