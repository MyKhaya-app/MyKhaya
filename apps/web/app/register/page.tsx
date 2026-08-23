"use client";
export const dynamic = "force-dynamic";
import { FormEvent, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { api, ApiError } from "@mykhaya/api-client";
import { AuthCard } from "@/components/auth-card";
import { FormStatus } from "@/components/form-status";
import { intervalName } from "@/components/billing-logic";
import { parseIntentFromParams, saveOnboardingIntent } from "@/components/onboarding-intent";
export default function Register() {
  const router = useRouter(),
    params = useSearchParams();
  const invitation = params.get("invitation");
  const calendarShare = params.get("calendar_share");
  // Plan/interval carried from the public pricing section (or a direct
  // /signup?plan=family&interval=year link) are untrusted onboarding intent
  // only — see components/onboarding-intent.ts. An invited member joins an
  // existing Home and never gets asked to choose a plan for it, so intent is
  // ignored entirely on the invite path. Same reasoning for a calendar-share
  // recipient: a free account is all that's needed to accept one — see
  // docs on external Calendar Sharing.
  const intent =
    invitation || calendarShare
      ? null
      : parseIntentFromParams(params.get("plan"), params.get("interval"));
  const [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [inviteContext, setInviteContext] = useState<{
      group_name: string;
      invited_by_display_name: string;
      email: string;
    } | null>(null),
    [shareContext, setShareContext] = useState<{
      calendar_name: string;
      source_group_name: string;
      invited_by_display_name: string;
      recipient_email: string;
    } | null>(null);
  useEffect(() => {
    if (!invitation) return;
    api
      .previewInvitation(invitation)
      .then((result) => setInviteContext(result))
      .catch((reason: ApiError) => setError(reason.message));
  }, [invitation]);
  useEffect(() => {
    if (!calendarShare) return;
    api
      .previewCalendarShare(calendarShare)
      .then((result) => setShareContext(result))
      .catch((reason: ApiError) => setError(reason.message));
  }, [calendarShare]);
  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setBusy(true);
    setError("");
    const d = new FormData(e.currentTarget);
    if (d.get("password") !== d.get("confirm")) {
      setError("The passwords do not match.");
      setBusy(false);
      return;
    }
    try {
      const result = await api.post<{
        message: string;
        verification_required: boolean;
      }>("/auth/register", {
        email: d.get("email"),
        display_name: d.get("name"),
        password: d.get("password"),
        invitation_token: invitation,
      });
      if (intent && intent.plan === "family") saveOnboardingIntent(intent);
      const carry = invitation
        ? `invitation=${encodeURIComponent(invitation)}`
        : calendarShare
          ? `calendar_share=${encodeURIComponent(calendarShare)}`
          : "";
      router.push(
        result.verification_required
          ? carry
            ? `/verify-email?${carry}`
            : "/verify-email"
          : carry
            ? `/login?${carry}`
            : "/login",
      );
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : "We couldn’t create your account. Please try again.",
      );
    } finally {
      setBusy(false);
    }
  }
  return (
    <AuthCard
      title="Create your account"
      intro="A calm, private place for the people closest to you."
      footer={
        <span>
          Already have an account?{" "}
          <Link
            href={
              invitation
                ? `/login?invitation=${encodeURIComponent(invitation)}`
                : calendarShare
                  ? `/login?calendar_share=${encodeURIComponent(calendarShare)}`
                  : "/login"
            }
          >
            Sign in
          </Link>
        </span>
      }
    >
      {inviteContext && (
        <p className="notice success">
          {inviteContext.invited_by_display_name} invited you to join {inviteContext.group_name}.
        </p>
      )}
      {shareContext && (
        <p className="notice success">
          {shareContext.source_group_name} wants to share the &ldquo;{shareContext.calendar_name}
          &rdquo; calendar with you. Create a free account to view it — Family isn&rsquo;t needed.
        </p>
      )}
      {!inviteContext && !shareContext && intent?.plan === "family" && (
        <p className="notice success">
          You selected Family ({intervalName(intent.interval)} billing) — you&rsquo;ll confirm this
          after creating your Home.
        </p>
      )}
      <form onSubmit={submit}>
        <label>
          Your name
          <input name="name" autoComplete="name" required maxLength={100} />
        </label>
        <label>
          Email
          <input
            name="email"
            type="email"
            defaultValue={inviteContext?.email ?? shareContext?.recipient_email ?? ""}
            autoComplete="email"
            required
            maxLength={320}
          />
        </label>
        <label>
          Password <small>At least 12 characters</small>
          <input
            name="password"
            type="password"
            autoComplete="new-password"
            required
            minLength={12}
            maxLength={128}
          />
        </label>
        <label>
          Confirm password
          <input
            name="confirm"
            type="password"
            autoComplete="new-password"
            required
            minLength={12}
            maxLength={128}
          />
        </label>
        <FormStatus error={error} />
        <button disabled={busy}>
          {busy ? "Creating account…" : "Create account"}
        </button>
      </form>
    </AuthCard>
  );
}
