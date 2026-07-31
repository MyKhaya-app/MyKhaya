"use client";
export const dynamic = "force-dynamic";
import { FormEvent, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { api, ApiError } from "@mykhaya/api-client";
import { AuthCard } from "@/components/auth-card";
import { FormStatus } from "@/components/form-status";
export default function Login() {
  const router = useRouter(),
    params = useSearchParams();
  const [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
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
      const invitation = params.get("invitation");
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
  const invitation = params.get("invitation");
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
