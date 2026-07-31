"use client";
import { FormEvent, useState } from "react";
import Link from "next/link";
import { api } from "@mykhaya/api-client";
import { AuthCard } from "@/components/auth-card";
import { FormStatus } from "@/components/form-status";
export default function Forgot() {
  const [message, setMessage] = useState("");
  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const d = new FormData(e.currentTarget);
    const r = await api.post<{ message: string }>("/auth/forgot-password", {
      email: d.get("email"),
    });
    setMessage(r.message);
  }
  return (
    <AuthCard
      title="Reset your password"
      intro="We’ll send a secure link if the address belongs to an account."
      footer={<Link href="/login">Back to sign in</Link>}
    >
      <form onSubmit={submit}>
        <label>
          Email
          <input name="email" type="email" autoComplete="email" required />
        </label>
        <FormStatus message={message} />
        <button>Send reset link</button>
      </form>
    </AuthCard>
  );
}
