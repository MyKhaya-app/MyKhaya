"use client";
import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import { api, ApiError } from "@mykhaya/api-client";
import { Logo } from "@/components/logo";
import { FormStatus } from "@/components/form-status";
export default function Onboarding() {
  const router = useRouter();
  const [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setBusy(true);
    const d = new FormData(e.currentTarget);
    try {
      await api.post("/groups", { name: d.get("name") });
      router.push("/home");
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "We couldn’t create your Home.",
      );
      setBusy(false);
    }
  }
  return (
    <main className="onboarding">
      <Logo />
      <section>
        <p className="step">Your first Home</p>
        <h1>What do you call home?</h1>
        <p className="muted">
          Choose a warm, familiar name. You can change it later.
        </p>
        <form onSubmit={submit}>
          <label>
            Home name
            <input
              name="name"
              placeholder="Our Home"
              maxLength={100}
              required
              autoFocus
            />
          </label>
          <FormStatus error={error} />
          <button disabled={busy}>
            {busy ? "Creating Home…" : "Create our Home"}
          </button>
        </form>
      </section>
    </main>
  );
}
