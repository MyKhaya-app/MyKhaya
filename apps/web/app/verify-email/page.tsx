"use client";
export const dynamic = "force-dynamic";
import { useEffect, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { api, ApiError } from "@mykhaya/api-client";
import { AuthCard } from "@/components/auth-card";
import { FormStatus } from "@/components/form-status";
export default function VerifyEmail() {
  const params = useSearchParams(),
    token = params.get("token"),
    invitation = params.get("invitation");
  const [message, setMessage] = useState(
      token
        ? "Verifying your email…"
        : "We sent a verification link to your inbox.",
    ),
    [error, setError] = useState("");
  useEffect(() => {
    if (!token) return;
    api
      .post<{ message: string }>("/auth/verify-email", { token })
      .then((r) => setMessage(r.message))
      .catch((err: unknown) => {
        setMessage("");
        setError(
          err instanceof ApiError
            ? err.message
            : "We couldn’t verify this link.",
        );
      });
  }, [token]);
  return (
    <AuthCard
      title="Check your inbox"
      intro="Email verification keeps your Home private."
    >
      <FormStatus message={message} error={error} />
      <p className="hint">
        In local development, open Mailpit at <strong>localhost:8025</strong>.
      </p>
      <Link
        className="button full"
        href={
          invitation
            ? `/login?invitation=${encodeURIComponent(invitation)}`
            : "/login"
        }
      >
        Continue to sign in
      </Link>
    </AuthCard>
  );
}
