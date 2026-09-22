"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@mykhaya/api-client";
import { BottomSheet } from "@/components/bottom-sheet";

function nextPeriod(year: number, month: number) {
  const next = new Date(year, month, 1);
  return { year: next.getFullYear(), month: next.getMonth() + 1 };
}

export function BudgetMonthCopy({ homeId, year, month, onCreated, contextual = false }: { homeId: string; year: number; month: number; onCreated?: () => void; contextual?: boolean }) {
  const router = useRouter();
  const target = contextual ? { year, month } : nextPeriod(year, month);
  const source = new Date(year, month - 2, 1);
  const targetLabel = new Intl.DateTimeFormat("en-GB", { month: "long", year: "numeric" }).format(new Date(target.year, target.month - 1, 1));
  const [open, setOpen] = useState(false);
  const [fixed, setFixed] = useState(true);
  const [variable, setVariable] = useState(false);
  const [income, setIncome] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  async function create() {
    setSaving(true);
    setError("");
    try {
      await api.copyBudgetMonth(homeId, target.year, target.month, {
        copy_fixed_items: fixed,
        copy_variable_items: variable,
        copy_income_sources: income,
      });
      onCreated?.();
      setOpen(false);
      router.push(`/budget/categories?year=${target.year}&month=${target.month}`);
    } catch {
      setError("Couldn’t create the next month. Please try again.");
    } finally {
      setSaving(false);
    }
  }

  return <>
    <button type="button" className={contextual ? "budget-contextual-copy-trigger" : "budget-secondary-button"} onClick={() => setOpen(true)}><span><strong>Set up {targetLabel}</strong>{contextual && <small>Copy your fixed costs and income from {new Intl.DateTimeFormat("en-GB", { month: "long" }).format(source)}.</small>}</span>{contextual && <span aria-hidden="true">›</span>}</button>
    {open && <BottomSheet title={`Create ${targetLabel} budget`} onDismiss={() => !saving && setOpen(false)}>
      <div className="budget-copy-sheet">
        <p>Choose what to add. Existing values in {targetLabel} will be kept; this does not replace the month.</p>
        <label className="budget-sheet-toggle"><span>Copy fixed monthly costs</span><input type="checkbox" checked={fixed} onChange={(event) => setFixed(event.target.checked)} /></label>
        <label className="budget-sheet-toggle"><span>Copy variable budgets</span><input type="checkbox" checked={variable} onChange={(event) => setVariable(event.target.checked)} /></label>
        <label className="budget-sheet-toggle"><span>Copy income sources</span><input type="checkbox" checked={income} onChange={(event) => setIncome(event.target.checked)} /></label>
        {error && <p role="alert">{error}</p>}
        <button type="button" onClick={() => void create()} disabled={saving}>{saving ? "Creating…" : `Create ${targetLabel} plan`}</button>
      </div>
    </BottomSheet>}
  </>;
}
