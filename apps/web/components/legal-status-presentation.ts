import type { LegalDocumentStatus } from "@mykhaya/api-client";

export const LEGAL_DOCUMENT_DESCRIPTION: Record<string, string> = {
  terms: "Our terms for using MyKhaya.",
  privacy: "How we collect and use your information.",
  children_privacy: "Additional privacy information for children and managed accounts.",
  cookies: "How we use cookies and similar technologies.",
};

export function legalReadableDate(value: string | null): string | null {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(
    date,
  );
}

export type LegalRowPresentation = {
  label: string;
  dateLabel: string | null;
  tone: "satisfied" | "required" | "neutral";
};

/**
 * Never invents an acceptance the backend didn't record. `satisfied` with
 * no `last_accepted_at` means this document simply doesn't require an
 * explicit action (e.g. Cookies), not that it was silently "accepted" —
 * see mykhaya.legal._status_from_records, whose `required`/`satisfied`/
 * `last_accepted_at` fields this presentation is a direct, honest read of.
 */
export function presentAdultLegalStatus(entry: LegalDocumentStatus): LegalRowPresentation {
  if (!entry.satisfied) return { label: "Review required", dateLabel: null, tone: "required" };
  const verb = entry.action_verb === "acknowledge" ? "Acknowledged" : "Accepted";
  const when = legalReadableDate(entry.last_accepted_at);
  return when
    ? { label: verb, dateLabel: `${verb} on ${when}`, tone: "satisfied" }
    : { label: "Current", dateLabel: null, tone: "neutral" };
}

/**
 * An adult's own status for a child-audience document (Family &
 * Children's Privacy) is never "they accepted it" — it's the aggregate of
 * their guardian_authorisation record(s) across whichever children they
 * guard. An adult who guards no children at all sees "For reference": the
 * document is readable, but no personal action applies to them.
 */
export function presentGuardianLegalStatus(entries: LegalDocumentStatus[]): LegalRowPresentation {
  if (entries.length === 0) {
    return { label: "For reference", dateLabel: null, tone: "neutral" };
  }
  if (entries.some((entry) => !entry.satisfied)) {
    return { label: "Review required", dateLabel: null, tone: "required" };
  }
  const mostRecent = entries
    .map((entry) => entry.last_accepted_at)
    .filter((value): value is string => Boolean(value))
    .sort()
    .at(-1);
  const when = legalReadableDate(mostRecent ?? null);
  return when
    ? { label: "Authorised", dateLabel: `Authorised on ${when}`, tone: "satisfied" }
    : { label: "Current", dateLabel: null, tone: "neutral" };
}
