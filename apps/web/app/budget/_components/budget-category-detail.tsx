"use client";

import { FormEvent, useEffect, useState } from "react";
import { BarChart3, ChevronDown, ChevronLeft, ChevronRight, CircleDollarSign, ShoppingCart, WalletCards } from "lucide-react";
import { api, type BudgetCategory, type BudgetMonth, type BudgetSpendingEntry } from "@mykhaya/api-client";
import { BottomSheet } from "@/components/bottom-sheet";
import { BudgetAddAction } from "./budget-add-action";
import { BudgetEntrySheet, periodDate } from "./budget-entry-sheet";
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
  useEffect(() => { void api.budgetMonth(homeId, year, month).then((data) => setNote(data.categories.find((item) => item.category_id === categoryId)?.note ?? "")); }, [categoryId, homeId, month, year]);
  return <><button type="button" className="budget-action-row" onClick={() => setOpen(true)}><span className="budget-icon"><WalletCards size={20} /></span><strong>Budget notes</strong><ChevronRight size={20} /></button>{open && <BottomSheet title="Budget notes" onDismiss={() => setOpen(false)}><form className="budget-sheet-form" onSubmit={async (event) => { event.preventDefault(); await api.updateBudgetCategoryNote(homeId, year, month, categoryId, note); setOpen(false); }}><label htmlFor="budget-category-note">Optional note</label><textarea id="budget-category-note" value={note} onChange={(event) => setNote(event.target.value)} maxLength={1000} rows={5} placeholder="Add a note for this category" /><button type="submit">Save note</button></form></BottomSheet>}</>;
}

function Transactions({ entries }: { entries: BudgetSpendingEntry[] }) {
  return <section className="budget-transactions" aria-labelledby="budget-transactions-heading"><h2 id="budget-transactions-heading" className="budget-section-title">Transactions</h2>{entries.length ? <div className="budget-list">{entries.map((entry) => <div className="budget-transaction-row" key={entry.id}><span className="budget-icon"><ShoppingCart size={19} /></span><span className="budget-row-copy"><strong>{entry.description}</strong><small>{entry.spent_on}</small></span><strong>{money(entry.amount)}</strong></div>)}</div> : <p className="budget-note">No spending recorded yet</p>}</section>;
}

export function BudgetCategoryDetail({ homeId, categoryId }: { homeId: string; categoryId: string }) {
  const [period, setPeriod] = useState(() => periodNow());
  const [month, setMonth] = useState<BudgetMonth | null>(null);
  const [category, setCategory] = useState<BudgetCategory | null>(null);
  const [entries, setEntries] = useState<BudgetSpendingEntry[]>([]);
  const [sheet, setSheet] = useState<"plan" | "actual" | null>(null);
  const [quickOpen, setQuickOpen] = useState(false);
  const [planned, setPlanned] = useState("0");
  const [actual, setActual] = useState("0");
  const [source, setSource] = useState<"manual" | "entries">("manual");
  const [entryOpen, setEntryOpen] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);

  const reload = () => {
    void Promise.all([api.budgetCategories(homeId), api.budgetMonth(homeId, period.year, period.month), api.budgetEntries(homeId, period)])
      .then(([categories, nextMonth, nextEntries]) => {
        setCategory(categories.find((item) => item.id === categoryId) ?? null);
        setMonth(nextMonth);
        setEntries(nextEntries.filter((entry) => entry.category_id === categoryId).sort((a, b) => b.spent_on.localeCompare(a.spent_on) || b.id.localeCompare(a.id)));
        const row = nextMonth.categories.find((item) => item.category_id === categoryId);
        if (row) { setPlanned(String(row.planned_amount)); setActual(String(row.manual_actual ?? row.actual_amount)); setSource(row.actual_source); }
      }).catch(() => { setMonth(null); setEntries([]); });
  };

  useEffect(() => { reload(); }, [categoryId, homeId, period.month, period.year, refreshKey]);
  const row = month?.categories.find((item) => item.category_id === categoryId);
  if (!row) return <><section className="budget-hero"><div><p className="budget-eyebrow">Budget</p><h1>{category?.name ?? "Category"}</h1><p>Optional spending detail sits under your plan.</p></div><div className="budget-artwork" aria-hidden="true"><img src="/images/PiggyBank_Budget_Image.png" alt="" /></div></section><BudgetTabs /><Period {...period} onChange={(year, month) => setPeriod({ year, month })} /><p role="status">Loading category details…</p></>;
  const remaining = Math.max(row.planned_amount - row.actual_amount, 0);
  const usage = Math.min((row.actual_amount / Math.max(row.planned_amount, 1)) * 100, 100);
  return <>
    <section className="budget-hero"><div><p className="budget-eyebrow">Budget</p><h1>{row.category_name}</h1><p>Optional spending detail sits under your plan.</p></div><div className="budget-artwork" aria-hidden="true"><img src="/images/PiggyBank_Budget_Image.png" alt="" /></div></section>
    <BudgetTabs />
    <Period {...period} onChange={(year, month) => setPeriod({ year, month })} />
    <section className="budget-detail-stats"><Stat label="Planned" value={money(row.planned_amount)} icon={CircleDollarSign} /><Stat label="Actual" value={money(row.actual_amount)} icon={BarChart3} /><Stat label="Remaining" value={money(remaining)} icon={CircleDollarSign} /></section>
    <div className="budget-usage-card"><strong>{row.actual_amount > 0 ? `${Math.round(usage)}% used` : "No spending yet"}</strong><span className="budget-progress"><span style={{ width: `${usage}%` }} /></span></div>
    <button type="button" className="budget-quick-actions-toggle" aria-expanded={quickOpen} onClick={() => setQuickOpen((open) => !open)}><strong>Quick actions</strong><ChevronDown size={20} aria-hidden="true" /></button>
    {quickOpen && <div className="budget-list budget-quick-actions"><button type="button" className="budget-action-row" onClick={() => setSheet("plan")}><span className="budget-icon"><CircleDollarSign size={20} /></span><strong>Edit planned amount</strong><ChevronRight size={20} /></button><button type="button" className="budget-action-row" onClick={() => setSheet("actual")}><span className="budget-icon"><BarChart3 size={20} /></span><strong>Update actual amount</strong><ChevronRight size={20} /></button><button type="button" className="budget-action-row" onClick={() => setEntryOpen(true)}><span className="budget-icon"><ShoppingCart size={20} /></span><strong>Add spending entry</strong><ChevronRight size={20} /></button><NotesAction homeId={homeId} categoryId={categoryId} year={period.year} month={period.month} /></div>}
    <Transactions entries={entries} />
    <BudgetItemList key={refreshKey} homeId={homeId} categoryId={categoryId} year={period.year} month={period.month} onRefresh={() => setRefreshKey((value) => value + 1)} />
    <BudgetAddAction homeId={homeId} onRefresh={() => setRefreshKey((value) => value + 1)} onSpending={() => setEntryOpen(true)} />
    {entryOpen && <BudgetEntrySheet homeId={homeId} initialCategoryId={categoryId} initialSpentOn={periodDate(period)} onClose={() => setEntryOpen(false)} onSaved={() => { setEntryOpen(false); setRefreshKey((value) => value + 1); }} />}
    {sheet === "plan" && <BottomSheet title="Edit planned amount" onDismiss={() => setSheet(null)}><form className="budget-sheet-form" onSubmit={async (event) => { event.preventDefault(); await api.updateBudgetPlan(homeId, period.year, period.month, categoryId, Number(planned)); reload(); setSheet(null); }}><label htmlFor="planned-amount">Planned amount (per month)</label><input id="planned-amount" type="number" min="0" step="0.01" value={planned} onChange={(event) => setPlanned(event.target.value)} required /><button type="submit">Save plan</button></form></BottomSheet>}
    {sheet === "actual" && <BottomSheet title="Update actual amount" onDismiss={() => setSheet(null)}><form className="budget-sheet-form" onSubmit={async (event: FormEvent) => { event.preventDefault(); await api.updateBudgetActual(homeId, period.year, period.month, categoryId, source === "manual" ? { source, manual_actual: Number(actual) } : { source }); reload(); setSheet(null); }}><label htmlFor="actual-source">Actual source</label><select id="actual-source" value={source} onChange={(event) => setSource(event.target.value as "manual" | "entries")}><option value="manual">Manual amount</option><option value="entries">Spending entries</option></select>{source === "manual" && <><label htmlFor="manual-actual">Actual this month</label><input id="manual-actual" type="number" min="0" step="0.01" value={actual} onChange={(event) => setActual(event.target.value)} /></>}<button type="submit">Save actual</button></form></BottomSheet>}
  </>;
}
