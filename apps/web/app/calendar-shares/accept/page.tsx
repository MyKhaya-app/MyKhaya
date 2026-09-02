"use client";
export const dynamic = "force-dynamic";

import { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { api, ApiError } from "@mykhaya/api-client";
import type { CalendarSharePreview } from "@mykhaya/shared-types";
import { AppShellContent } from "@/components/app-shell";
import { FormStatus } from "@/components/form-status";

type Outcome = { kind: "accepted" } | { kind: "declined" };

// The landing point for an external Calendar Share invitation, reached either
// straight from the invitation email (?token=...) or via login/register's
// signup-preserving redirect (see app/login/page.tsx, app/register/page.tsx).
// Deliberately not folded into the household invitation accept flow
// (login's silent /invitations/accept) — a share recipient chooses
// notification/briefing preferences as part of accepting, per product spec.
export default function AcceptCalendarSharePage() {
  const router = useRouter();
  const params = useSearchParams();
  const token = params.get("token");
  const [preview, setPreview] = useState<CalendarSharePreview | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const [notificationPreference, setNotificationPreference] =
    useState<"all" | "important" | "off">("all");
  const [includeInBriefing, setIncludeInBriefing] = useState(true);

  useEffect(() => {
    if (!token) {
      setError("This invitation link is missing its token.");
      return;
    }
    api
      .previewCalendarShare(token)
      .then(setPreview)
      .catch((cause: unknown) => {
        setError(
          cause instanceof ApiError
            ? cause.message
            : "This invitation could not be loaded.",
        );
      });
  }, [token]);

  async function accept() {
    if (!token || busy) return;
    setBusy(true);
    setError("");
    try {
      await api.acceptCalendarShare(token, {
        notification_preference: notificationPreference,
        include_in_briefing: includeInBriefing,
      });
      setOutcome({ kind: "accepted" });
    } catch (cause) {
      setError(
        cause instanceof ApiError ? cause.message : "We could not accept that invitation.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function decline() {
    if (!token || busy) return;
    if (!window.confirm("Decline this calendar share?")) return;
    setBusy(true);
    setError("");
    try {
      await api.declineCalendarShare(token);
      setOutcome({ kind: "declined" });
    } catch (cause) {
      setError(
        cause instanceof ApiError ? cause.message : "We could not decline that invitation.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <AppShellContent>
      <main className="standard-page">
        <div className="page-heading">
          <div>
            <p className="eyebrow">Calendar sharing</p>
            <h1>Shared calendar invitation</h1>
          </div>
        </div>

        <FormStatus error={error} />

        {outcome?.kind === "accepted" && (
          <section className="card details">
            <h2>You&rsquo;re connected</h2>
            <p>
              &ldquo;{preview?.calendar_name}&rdquo; is now in your calendar list, shared by{" "}
              {preview?.source_group_name}.
            </p>
            <button type="button" onClick={() => router.push("/calendar/shared")}>
              View shared calendars
            </button>
          </section>
        )}

        {outcome?.kind === "declined" && (
          <section className="card details">
            <h2>Invitation declined</h2>
            <p>You won&rsquo;t get access to that calendar.</p>
            <button type="button" onClick={() => router.push("/home")}>
              Go to Home
            </button>
          </section>
        )}

        {!outcome && preview && (
          <section className="card details">
            <h2>
              {preview.source_group_name} wants to share &ldquo;{preview.calendar_name}&rdquo;
            </h2>
            <p className="muted">
              Invited by {preview.invited_by_display_name} ·{" "}
              {preview.permission === "manage" ? "Can add & edit" : "Can view"}
            </p>
            <p>
              {preview.permission === "manage"
                ? "You'll be able to view this calendar and add or edit its events. Nothing else about this Home is shared with you."
                : "You'll be able to view this calendar's events, receive reminders and include them in your morning briefing. Nothing else about this Home is shared with you."}
            </p>

            <label>
              Notifications for this calendar
              <select
                value={notificationPreference}
                onChange={(event) =>
                  setNotificationPreference(
                    event.target.value as "all" | "important" | "off",
                  )
                }
              >
                <option value="all">All activity</option>
                <option value="important">Important changes only</option>
                <option value="off">Off</option>
              </select>
            </label>
            <label className="check-row">
              <input
                type="checkbox"
                checked={includeInBriefing}
                onChange={(event) => setIncludeInBriefing(event.target.checked)}
              />
              Include in my morning briefing
            </label>

            <div className="actions">
              <button type="button" disabled={busy} onClick={() => void accept()}>
                {busy ? "Accepting…" : "Accept"}
              </button>
              <button
                type="button"
                className="secondary"
                disabled={busy}
                onClick={() => void decline()}
              >
                Decline
              </button>
            </div>
          </section>
        )}
      </main>
    </AppShellContent>
  );
}
