export type LayoutIssue = {
  kind: string;
  element: string;
  message: string;
  [detail: string]: unknown;
};

export type LayoutReport = {
  viewport: { width: number; height: number };
  documentWidth?: number;
  issues: LayoutIssue[];
  advisories: LayoutIssue[];
  metrics: Record<string, unknown>[];
};

export type LayoutInspectionOptions = {
  rootSelector?: string | null;
  checkReachability?: boolean;
  overlay?: { right: number; top: number } | null;
  intendedScrollers?: string[];
  visibleHeight?: number | null;
  acceptedOverflow?: string[];
};

export function inspectLayoutInPage(options?: LayoutInspectionOptions): LayoutReport;
export const INTENDED_HORIZONTAL_SCROLLERS: string[];
export const ACCEPTED_CONTAINMENT_EXCEPTIONS: string[];
