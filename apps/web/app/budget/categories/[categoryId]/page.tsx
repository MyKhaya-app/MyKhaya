"use client";

import { use } from "react";
import { BudgetModuleSheets as BudgetModule } from "../../_components/budget-module-sheets";

export default function BudgetCategoryDetailPage({ params }: { params: Promise<{ categoryId: string }> }) {
  const { categoryId } = use(params);
  return <BudgetModule screen="category-detail" categoryId={categoryId} />;
}
