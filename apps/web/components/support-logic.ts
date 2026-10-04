// Pure display logic for MyKhaya Support ticket enums (see
// apps/api/mykhaya/models.py's SupportTicket* StrEnums) — the shared
// frontend mirror of that backend representation (matching this codebase's
// existing hand-mirrored-enum convention, e.g. WidgetEvent/CalendarLayout),
// so app-area/type/status/priority values are never re-listed as scattered
// string literals. Originally built for Platform Control Centre's Support
// queue (Phase 2B); reused as-is by the consumer Report a bug form (Phase
// 2D) for the same app-area enum and priority values — only
// `CcBadgeTone`-typed exports are PCC-specific (a type-only import, erased
// at compile time, so importing this file adds no PCC code to the consumer
// bundle). Kept separate from page components so it can be unit-tested
// directly (this repo has no component-rendering test infra for Control
// Centre pages; see platform-mfa-logic.test.ts for the established
// pattern), mirroring status-incidents-logic.ts's shape. Never re-derives
// ticket state — that stays server-side; this only turns an already-resolved
// enum value into something to show a person.

import type { CcBadgeTone } from "./control-centre/badge";

export type SupportTicketTypeValue = "bug" | "support" | "feedback";
export type SupportTicketStatusValue =
  | "open"
  | "in_progress"
  | "waiting_for_user"
  | "resolved"
  | "closed";
export type SupportTicketPriorityValue = "normal" | "elevated" | "blocking";
export type SupportTicketSourceValue = "ios" | "android" | "web" | "desktop_web";
export type SupportTicketAppAreaValue =
  | "home"
  | "calendar"
  | "family"
  | "nudges"
  | "lists"
  | "meals"
  | "budget"
  | "account"
  | "notifications"
  | "more"
  | "other";

const TYPE_LABELS: Record<SupportTicketTypeValue, string> = {
  bug: "Bug report",
  support: "Support request",
  feedback: "Feedback",
};

const STATUS_LABELS: Record<SupportTicketStatusValue, string> = {
  open: "Open",
  in_progress: "In progress",
  waiting_for_user: "Waiting for user",
  resolved: "Resolved",
  closed: "Closed",
};

const PRIORITY_LABELS: Record<SupportTicketPriorityValue, string> = {
  normal: "Normal",
  elevated: "Elevated",
  blocking: "Blocking",
};

const SOURCE_LABELS: Record<SupportTicketSourceValue, string> = {
  ios: "iOS",
  android: "Android",
  web: "Web",
  desktop_web: "Desktop web",
};

const APP_AREA_LABELS: Record<SupportTicketAppAreaValue, string> = {
  home: "Home",
  calendar: "Calendar",
  family: "Family",
  nudges: "Nudges",
  lists: "Lists",
  meals: "Meals",
  budget: "Budget",
  account: "Account",
  notifications: "Notifications",
  more: "More",
  other: "Other",
};

export function ticketTypeLabel(value: string): string {
  return TYPE_LABELS[value as SupportTicketTypeValue] ?? value;
}

export function ticketStatusLabel(value: string): string {
  return STATUS_LABELS[value as SupportTicketStatusValue] ?? value;
}

export function ticketPriorityLabel(value: string): string {
  return PRIORITY_LABELS[value as SupportTicketPriorityValue] ?? value;
}

export function ticketSourceLabel(value: string): string {
  return SOURCE_LABELS[value as SupportTicketSourceValue] ?? value;
}

export function ticketAppAreaLabel(value: string | null): string {
  if (!value) return "—";
  return APP_AREA_LABELS[value as SupportTicketAppAreaValue] ?? value;
}

export function ticketStatusTone(value: string): CcBadgeTone {
  switch (value as SupportTicketStatusValue) {
    case "open":
      return "info";
    case "in_progress":
      return "warning";
    case "waiting_for_user":
      return "neutral";
    case "resolved":
    case "closed":
      return "success";
    default:
      return "neutral";
  }
}

export function ticketPriorityTone(value: string): CcBadgeTone {
  switch (value as SupportTicketPriorityValue) {
    case "blocking":
      return "danger";
    case "elevated":
      return "warning";
    case "normal":
    default:
      return "neutral";
  }
}

export function ticketTypeTone(value: string): CcBadgeTone {
  switch (value as SupportTicketTypeValue) {
    case "bug":
      return "danger";
    case "support":
      return "info";
    case "feedback":
      return "neutral";
    default:
      return "neutral";
  }
}

export const TICKET_STATUS_OPTIONS: SupportTicketStatusValue[] = [
  "open",
  "in_progress",
  "waiting_for_user",
  "resolved",
  "closed",
];

export const TICKET_PRIORITY_OPTIONS: SupportTicketPriorityValue[] = [
  "normal",
  "elevated",
  "blocking",
];

export const TICKET_TYPE_OPTIONS: SupportTicketTypeValue[] = ["bug", "support", "feedback"];

export const TICKET_SOURCE_OPTIONS: SupportTicketSourceValue[] = [
  "ios",
  "android",
  "web",
  "desktop_web",
];

export const TICKET_APP_AREA_OPTIONS: SupportTicketAppAreaValue[] = [
  "home",
  "calendar",
  "family",
  "nudges",
  "lists",
  "meals",
  "budget",
  "account",
  "notifications",
  "more",
  "other",
];

export const APP_AREA_OPTIONS: { value: SupportTicketAppAreaValue; label: string }[] =
  TICKET_APP_AREA_OPTIONS.map((value) => ({ value, label: APP_AREA_LABELS[value] }));

// --- My support requests (consumer-only) ----------------------------------

// A ticket the requester can still add to. Never used to gate the backend
// (routers.support.add_message accepts a reply regardless of status — this
// is purely a frontend courtesy so a person isn't invited to type into a
// closed conversation); see help-support/requests/[id]/page.tsx.
export function isActiveTicketStatus(status: string): boolean {
  return status === "open" || status === "in_progress" || status === "waiting_for_user";
}

// Used by the Help & Support hub's "My support requests" card (Part C) —
// reuses the same list response the requests page itself fetches, never a
// second/dedicated count endpoint. `null` means "not yet known" (still
// loading, or the request failed), which the caller renders as no count
// rather than 0.
export function openTicketCount(
  tickets: { status: string }[] | null,
): number | null {
  if (tickets === null) return null;
  return tickets.filter((ticket) => isActiveTicketStatus(ticket.status)).length;
}

// A small, consumer-safe status tone — deliberately not CcBadgeTone (PCC's
// own component/type), so this file's consumer half never depends on PCC
// styling even indirectly. See .support-status-pill in app/styles.css.
export type SupportStatusTone = "info" | "warning" | "neutral" | "success";

export function ticketStatusConsumerTone(value: string): SupportStatusTone {
  switch (value as SupportTicketStatusValue) {
    case "open":
      return "info";
    case "in_progress":
      return "warning";
    case "waiting_for_user":
      return "neutral";
    case "resolved":
    case "closed":
      return "success";
    default:
      return "neutral";
  }
}

// Mirrors control-centre/platform-format.ts's relativeTime shape but kept
// local — the consumer app never imports from components/platform-format.ts
// (a PCC-named module) even for a function this small and generic.
export function relativeTimeFromNow(value: string): string {
  const elapsed = new Date(value).getTime() - Date.now();
  if (Number.isNaN(elapsed)) return "Unavailable";
  const formatter = new Intl.RelativeTimeFormat("en-GB", { numeric: "auto" });
  const units: [Intl.RelativeTimeFormatUnit, number][] = [
    ["day", 86_400_000],
    ["hour", 3_600_000],
    ["minute", 60_000],
  ];
  for (const [unit, milliseconds] of units) {
    if (Math.abs(elapsed) >= milliseconds) return formatter.format(Math.round(elapsed / milliseconds), unit);
  }
  return "just now";
}
