"use client";
export const dynamic = "force-dynamic";
import { FormEvent, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { api, ApiError } from "@mykhaya/api-client";
import { AuthCard } from "@/components/auth-card";
import { FormStatus } from "@/components/form-status";

function formText(data: FormData, name: string) {
  const value = data.get(name);
  return typeof value === "string" ? value : "";
}

export default function ChildLogin() {
  const router = useRouter();
  const [error, setError] = useState(""),
    [busy, setBusy] = useState(false);

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setBusy(true);
    setError("");
    const d = new FormData(e.currentTarget);
    try {
      await api.childLogin({
        home_code: formText(d, "home_code"),
        username: formText(d, "username"),
        pin: formText(d, "pin"),
      });
      router.push("/home");
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
      title="Child sign in"
      intro="Ask a grown-up for your Home code if you don’t know it."
      footer={
        <span>
          Not a child? <Link href="/login">Back to sign in</Link>
        </span>
      }
    >
      <form onSubmit={submit}>
        <label>
          Home code
          <input
            name="home_code"
            autoComplete="off"
            autoCapitalize="characters"
            required
            minLength={4}
            maxLength={10}
          />
        </label>
        <label>
          Username
          <input
            name="username"
            autoComplete="off"
            required
            minLength={1}
            maxLength={24}
          />
        </label>
        <label>
          PIN
          <input
            name="pin"
            type="password"
            inputMode="numeric"
            pattern="[0-9]*"
            autoComplete="off"
            required
            minLength={4}
            maxLength={6}
          />
        </label>
        <FormStatus error={error} />
        <button disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button>
      </form>
    </AuthCard>
  );
}
