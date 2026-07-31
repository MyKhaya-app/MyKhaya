"use client";
export const dynamic = "force-dynamic";
import { FormEvent, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { api, ApiError } from "@mykhaya/api-client";
import { AuthCard } from "@/components/auth-card";
import { FormStatus } from "@/components/form-status";
export default function Reset() {
  const token = useSearchParams().get("token");
  const [message, setMessage] = useState(""),
    [error, setError] = useState("");
  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const d = new FormData(e.currentTarget);
    if (d.get("password") !== d.get("confirm")) {
      setError("The passwords do not match.");
      return;
    }
    try {
      const r = await api.post<{ message: string }>("/auth/reset-password", {
        token,
        password: d.get("password"),
      });
      setMessage(r.message);
      setError("");
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : "We couldn’t reset your password.",
      );
    }
  }
  return (
    <AuthCard
      title="Choose a new password"
      intro="Use at least 12 characters that you don’t use elsewhere."
      footer={message ? <Link href="/login">Sign in</Link> : undefined}
    >
      <form onSubmit={submit}>
        <label>
          New password
          <input
            name="password"
            type="password"
            minLength={12}
            maxLength={128}
            autoComplete="new-password"
            required
          />
        </label>
        <label>
          Confirm password
          <input
            name="confirm"
            type="password"
            minLength={12}
            maxLength={128}
            autoComplete="new-password"
            required
          />
        </label>
        <FormStatus message={message} error={error} />
        <button disabled={!token}>Change password</button>
      </form>
    </AuthCard>
  );
}
