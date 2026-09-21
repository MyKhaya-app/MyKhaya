import { use } from "react";
import { BudgetModuleSheets as BudgetModule } from "../../../_components/budget-module-sheets";

export default function BudgetEditEntryPage({ params }: { params: Promise<{ entryId: string }> }) {
  const { entryId } = use(params);
  return <BudgetModule screen="entry-edit" entryId={entryId} />;
}
