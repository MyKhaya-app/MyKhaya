import type { CcBadgeTone } from "./control-centre/badge";

export type LegalAudience = "adult" | "child";
export type LegalDocumentScope = "global" | "founding_beta";
export type LegalActionVerb = "accept" | "acknowledge";
export type LegalVersionStatus =
  | "draft"
  | "scheduled"
  | "published"
  | "superseded";
export type LegalReacceptanceScope =
  | "none"
  | "new_users_only"
  | "all_existing_users";

export type LegalDocumentVersionSummary = {
  id: string;
  version: string;
  version_sequence: number;
  status: LegalVersionStatus;
  effective_date: string | null;
  published_at: string | null;
  updated_at: string;
  reacceptance_scope: LegalReacceptanceScope;
  change_summary: string | null;
  acceptance_count: number;
  is_test?: boolean;
};

export type LegalDocumentVersionDetail = LegalDocumentVersionSummary & {
  content_markdown: string;
  created_by_administrator_id: string | null;
  updated_by_administrator_id: string | null;
  published_by_administrator_id: string | null;
  superseded_at: string | null;
  superseded_by_version_id: string | null;
};

export type LegalDocument = {
  id: string;
  key: string;
  display_name: string;
  audience: LegalAudience;
  scope: LegalDocumentScope;
  action_verb: LegalActionVerb;
  acceptance_required: boolean;
  archived_at: string | null;
  published_version: LegalDocumentVersionSummary | null;
  test_published_version?: LegalDocumentVersionSummary | null;
  draft_version: LegalDocumentVersionSummary | null;
};

export function versionStatusLabel(status: LegalVersionStatus): string {
  switch (status) {
    case "draft":
      return "Draft";
    case "scheduled":
      return "Scheduled";
    case "published":
      return "Published";
    case "superseded":
      return "Superseded";
  }
}

export function versionStatusTone(status: LegalVersionStatus): CcBadgeTone {
  switch (status) {
    case "draft":
      return "warning";
    case "scheduled":
      return "info";
    case "published":
      return "success";
    case "superseded":
      return "neutral";
  }
}

export function audienceLabel(audience: LegalAudience): string {
  return audience === "adult" ? "Adult" : "Child (via guardian)";
}

export function documentScopeLabel(scope: LegalDocumentScope): string {
  return scope === "founding_beta" ? "Founding Beta" : "Global";
}

export function actionVerbLabel(verb: LegalActionVerb): string {
  return verb === "accept" ? "Accept" : "Acknowledge";
}

export function reacceptanceScopeLabel(scope: LegalReacceptanceScope): string {
  switch (scope) {
    case "none":
      return "No re-acceptance required";
    case "new_users_only":
      return "New users only";
    case "all_existing_users":
      return "All existing users";
  }
}

export function reacceptanceScopeDescription(
  scope: LegalReacceptanceScope,
): string {
  switch (scope) {
    case "none":
      return "Existing users will not be interrupted. The new version becomes the current version for future viewing.";
    case "new_users_only":
      return "Users joining after this version becomes effective must complete the applicable legal action.";
    case "all_existing_users":
      return "Existing applicable users will be required to complete the applicable legal action.";
  }
}

export const REACCEPTANCE_SCOPE_OPTIONS: LegalReacceptanceScope[] = [
  "none",
  "new_users_only",
  "all_existing_users",
];
