"use client";
export const dynamic = "force-dynamic";
import { FormEvent, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { api, ApiError } from "@mykhaya/api-client";
import { AuthCard } from "@/components/auth-card";
import { FormStatus } from "@/components/form-status";
export default function Login() {
  const router = useRouter(),
    params = useSearchParams();
  const invitation = params.get("invitation");
  const [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [inviteContext, setInviteContext] = useState<{
      group_name: string;
      invited_by_display_name: string;
      email: string;
    } | null>(null);

  useEffect(() => {
    if (!invitation) return;
    api
      .previewInvitation(invitation)
      .then((result) => setInviteContext(result))
      .catch((reason: ApiError) => setError(reason.message));
  }, [invitation]);
  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setBusy(true);
    setError("");
    const d = new FormData(e.currentTarget);
    try {
      await api.post("/auth/login", {
        email: d.get("email"),
        password: d.get("password"),
      });
      if (invitation)
        await api.post("/invitations/accept", { token: invitation });
      router.push((await api.homes()).length ? "/home" : "/onboarding");
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : "We couldn’t sign you in. Please try again.",
      );
    } finally {
      setBusy(false);
    }
  }
  return (
    <AuthCard
      title="Welcome back"
      intro="Sign in to see what’s happening at Home."
      footer={
        <>
          <Link href="/forgot-password">Forgot password?</Link>
          <span>
            New here?{" "}
            <Link
              href={
                invitation
                  ? `/register?invitation=${encodeURIComponent(invitation)}`
                  : "/register"
              }
            >
              Create an account
            </Link>
          </span>
        </>
      }
    >
      {inviteContext && (
        <p className="notice success">
          Continue signing in to join {inviteContext.group_name}.
        </p>
      )}
      <form onSubmit={submit}>
        <label>
          Email
          <input
            name="email"
            type="email"
            autoComplete="email"
            required
            maxLength={320}
          />
        </label>
        <label>
          Password
          <input
            name="password"
            type="password"
            autoComplete="current-password"
            required
            maxLength={128}
          />
        </label>
        <FormStatus error={error} />
        <button disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button>
      </form>
    </AuthCard>
  );
}
