import type { ManagedDemoAccess, ManagedDemoTemplate, ManagedDemoType } from "@/components/platform-types";

export const TEMPLATE_LABELS: Record<ManagedDemoType, string> = {
  apple_review: "Apple Review",
  demo: "Family Demo",
  ultimate_demo: "Ultimate Demo",
  free_demo: "Free Plan Demo",
  qa_test: "QA Test",
};

export const ACCESS_LABELS: Record<ManagedDemoAccess, string> = {
  free: "Free",
  family: "Family",
  ultimate: "Ultimate",
};

// Used only until GET /demo-test-homes/templates answers (or if it fails), so
// the form stays usable. Module lists always come from the server, which
// derives them from the plan's real entitlements.
export const DEFAULT_TEMPLATE: ManagedDemoTemplate = {
  fixture_type: "apple_review",
  label: "Apple Review",
  access: "family",
  showcase: false,
  showcase_modules: [],
};
export const FALLBACK_TEMPLATES: ManagedDemoTemplate[] = [
  DEFAULT_TEMPLATE,
  { fixture_type: "demo", label: "Family Demo", access: "family", showcase: true, showcase_modules: [] },
  { fixture_type: "ultimate_demo", label: "Ultimate Demo", access: "ultimate", showcase: true, showcase_modules: [] },
  { fixture_type: "free_demo", label: "Free Plan Demo", access: "free", showcase: false, showcase_modules: [] },
];

export function isTemplateList(value: unknown): value is ManagedDemoTemplate[] {
  return (
    Array.isArray(value) &&
    value.every(
      (row) =>
        typeof row === "object" &&
        row !== null &&
        "fixture_type" in row &&
        "showcase_modules" in row &&
        Array.isArray((row as ManagedDemoTemplate).showcase_modules),
    )
  );
}

export function todayIso(): string {
  const now = new Date();
  const local = new Date(now.getTime() - now.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 10);
}

export function formatReferenceDate(value: string | null | undefined): string {
  if (!value) return "—";
  return new Date(`${value}T00:00:00`).toLocaleDateString(undefined, {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}
