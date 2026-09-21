import { use } from "react";
import { BudgetModule } from "../../../_components/budget-module-wired";

export default function BudgetEditEntryPage({ params }: { params: Promise<{ entryId: string }> }) {
  const { entryId } = use(params);
  return <BudgetModule screen="entry-edit" entryId={entryId} />;
}
