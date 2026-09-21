"use client";

import { use } from "react";
import { BudgetModule } from "../../_components/budget-module-wired";

export default function BudgetCategoryDetailPage({ params }: { params: Promise<{ categoryId: string }> }) {
  const { categoryId } = use(params);
  return <BudgetModule screen="category-detail" categoryId={categoryId} />;
}
