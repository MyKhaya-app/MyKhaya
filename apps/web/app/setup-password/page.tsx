"use client";

export const dynamic = "force-dynamic";

import { FormEvent, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { api, ApiError } from "@mykhaya/api-client";
import { AuthCard } from "@/components/auth-card";
import { FormStatus } from "@/components/form-status";

export default function SetupPassword() {
  const token = useSearchParams().get("token");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    if (data.get("password") !== data.get("confirm")) {
      setError("The passwords do not match.");
      return;
    }
    try {
      const response = await api.post<{ message: string }>("/auth/setup-password", {
        token,
        password: data.get("password"),
      });
      setMessage(response.message);
      setError("");
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "We couldn’t set up your password.");
    }
  }

  return (
    <AuthCard
      title="Set up your MyKhaya password"
      intro="Choose a password to sign in with your email address as well as your connected sign-in methods."
      footer={message ? <Link href="/login">Sign in</Link> : undefined}
    >
      <form onSubmit={submit}>
        <label>
          New password
          <input name="password" type="password" minLength={12} maxLength={128} autoComplete="new-password" required />
        </label>
        <label>
          Confirm password
          <input name="confirm" type="password" minLength={12} maxLength={128} autoComplete="new-password" required />
        </label>
        <FormStatus message={message} error={error} />
        <button disabled={!token}>Set password</button>
      </form>
    </AuthCard>
  );
}
