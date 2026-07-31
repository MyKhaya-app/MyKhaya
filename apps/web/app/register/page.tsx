"use client";
export const dynamic = "force-dynamic";
import { FormEvent, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { api, ApiError } from "@mykhaya/api-client";
import { AuthCard } from "@/components/auth-card";
import { FormStatus } from "@/components/form-status";
export default function Register() {
  const router = useRouter(),
    params = useSearchParams();
  const [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
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
      });
      const invitation = params.get("invitation");
      router.push(
        result.verification_required
          ? invitation
            ? `/verify-email?invitation=${encodeURIComponent(invitation)}`
            : "/verify-email"
          : invitation
            ? `/login?invitation=${encodeURIComponent(invitation)}`
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
  const invitation = params.get("invitation");
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
                : "/login"
            }
          >
            Sign in
          </Link>
        </span>
      }
    >
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
